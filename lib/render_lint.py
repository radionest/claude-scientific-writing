"""Lint the rendered .docx — defects that materialize only in the render.

`lib.lint_prose` never sees table text or captions: `qmd_prose` skips fenced chunks
(where the generating f-strings and `#| tbl-cap:`/`#| fig-cap:` options live) and
markdown tables. This module extracts every paragraph and table cell from
word/document.xml and runs the canon's regex-kind rules over them — the render is
the only place that text exists as prose.

    python3 -m lib.render_lint <render.docx> [--qmd source.qmd] [--json]

Regex entries only (check-kind rules see sentences/documents — wrong shape for
table fragments). `--qmd` attaches a `qmd` hint to each finding by searching the
source for the matched text: rendered values come from f-string placeholders, so an
exact miss falls back to the matched text with the rendered value stripped. Advisory by
design: exit 1 on error-severity findings, but no hook gates on it.

Beyond the regex rules, `_vertical_checks` reads paragraph styles and caption/mention
numbers: table and figure caption sequences (jumps, duplicates, reordering), mention↔caption ref
targets («табл. N»), heading-level skips by `Heading1…6` styles. All findings are warn;
the checks stay silent when the material is absent, so a non-Quarto .docx is not noise.
Cross-reference existence is checked only at the render — `#| label:` lives in fenced
chunks that `Document` never sees.

Regex application duplicates `lint_text`'s inner loop instead of reusing it:
`lint_text` routes through `extract_prose`, whose markdown filtering (tables,
fences) would drop the very lines this module exists to lint.
"""
from __future__ import annotations
import argparse, json, re, sys, xml.parsers.expat, zipfile, zlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator
from xml.etree import ElementTree as ET

from lib.docx_review import DocxError, _OLE_MAGIC, _parse_xml
from lib.lint_prose import ConfigError, Finding, effective_entries, load_entries
from lib.qmd_prose import _FENCE_RE

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# ISO 29500 Strict variant: every _W lookup would miss it, silently yielding zero units
_STRICT_W = "{http://purl.oclc.org/ooxml/wordprocessingml/main}"


@dataclass
class TextUnit:
    lineno: int  # document-wide paragraph ordinal — a .docx has no qmd line numbers
    kind: str    # "body" | "cell"
    ref: str     # "" for body, "tbl2 r1 c3" for a table cell
    text: str
    style: str = ""  # w:pStyle/@w:val of the paragraph — "" when unstyled


def _para_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(_W + "t"))


def _para_style(p: ET.Element) -> str:
    ppr = p.find(_W + "pPr")
    if ppr is None:
        return ""
    st = ppr.find(_W + "pStyle")
    return st.get(_W + "val", "") if st is not None else ""


def _iter_body_content(parent: Iterable[ET.Element]) -> Iterator[ET.Element]:
    """Direct w:p/w:tbl children, descending into container elements —
    Word-authored .docx wrap content in w:sdt content controls."""
    for el in parent:
        if el.tag in (_W + "p", _W + "tbl"):
            yield el
        else:
            yield from _iter_body_content(el)


def extract_units(path: Path) -> list[TextUnit]:
    """Body paragraphs + one unit per table cell, in document order.

    A cell unit flattens every paragraph inside the cell (nested tables included)
    into one space-joined text — a cell is one linting unit, not many lines.

    Fails closed (#96/#97/#98): anything short of a readable Transitional w:body —
    a missing body, a corrupt deflate stream, Strict OOXML namespaces — raises
    DocxError instead of yielding zero units and a lint-clean exit 0.
    """
    with path.open("rb") as fh:
        if fh.read(len(_OLE_MAGIC)) == _OLE_MAGIC:
            raise DocxError(f"{path}: устаревший .doc или зашифрованный DOCX (OLE-контейнер) — "
                            "пересохраните как .docx без пароля")
    try:
        with zipfile.ZipFile(path) as z:
            root = _parse_xml(z.read("word/document.xml"))
    except zipfile.BadZipFile as e:
        raise DocxError(f"{path}: не .docx (не zip-архив)") from e
    except zlib.error as e:
        raise DocxError(f"{path}: повреждённые сжатые данные внутри .docx — {e}") from e
    except KeyError as e:
        raise DocxError(f"{path}: в архиве нет части {e} — файл повреждён или это не .docx") from e
    except xml.parsers.expat.ExpatError as e:
        raise DocxError(f"{path}: повреждённый XML внутри .docx — {e}") from e
    except NotImplementedError as e:
        # zipfile raises it on unsupported compression, not on a password
        raise DocxError(f"{path}: неподдерживаемый метод сжатия внутри архива — {e}") from e
    except RuntimeError as e:
        raise DocxError(f"{path}: файл защищён паролем — расшифруйте его и повторите") from e

    if root.tag.startswith(_STRICT_W):
        raise DocxError(f"{path}: Strict OOXML не поддерживается — "
                        "пересохраните документ обычным .docx (Transitional)")
    body = root.find(_W + "body")
    if body is None:
        raise DocxError(f"{path}: в document.xml нет w:body — файл повреждён "
                        "или это не Word-документ")
    units: list[TextUnit] = []
    n = 0        # document-wide paragraph ordinal
    tbl_no = 0
    for el in _iter_body_content(body):
        if el.tag == _W + "p":
            n += 1
            units.append(TextUnit(n, "body", "", _para_text(el), _para_style(el)))
        elif el.tag == _W + "tbl":
            tbl_no += 1
            for r, tr in enumerate(el.findall(_W + "tr"), 1):
                for c, tc in enumerate(tr.findall(_W + "tc"), 1):
                    paras = [_para_text(p) for p in tc.iter(_W + "p")]
                    n += len(paras)
                    units.append(TextUnit(n, "cell", f"tbl{tbl_no} r{r} c{c}",
                                          " ".join(t for t in paras if t)))
    return units


def _qmd_lines(qmd: Path) -> list[tuple[str, bool]]:
    """(line text, inside-a-fenced-chunk) — the hint says whether the match sits
    in the code that generated it. Fence lines keep their raw number: they are
    appended too, so line numbering matches the file exactly."""
    out, in_fence = [], False
    for line in qmd.read_text(encoding="utf-8").splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
        out.append((line, in_fence))
    return out


def _hint(lines: list[tuple[str, bool]], matched: str) -> str:
    """`L12` / `L12 (chunk)` / "". Exact substring first; else the matched text
    with the rendered value stripped (digits, percent, brackets, dot, comma,
    spaces) — dash/colon separators stay as the anchor, >= 4 chars."""
    probes = [matched, matched.split("{", 1)[0].rstrip(" 0123456789%().,")]
    for probe in probes:
        if len(probe) < 4:
            continue
        for lineno, (text, in_chunk) in enumerate(lines, 1):
            if probe in text:
                return f"L{lineno}" + (" (chunk)" if in_chunk else "")
    return ""


# A caption is «Таблица N —/./: …» — the punctuation after the number keeps a prose
# sentence starting with «Таблица 2 показывает…» from being taken for a caption.
_CAPTION = re.compile(r"^\s*(таблиц[аы]|рисун\w*|рис\.|table|figure)\s*(\d+)\s*[-–—.:]", re.IGNORECASE)
# issue #88: «русский термин (code)» — a parenthesized group attached to a Cyrillic
# word decodes the Latin data codes inside it; only captions and table cells qualify.
_GLOSS = re.compile(r"[\u0400-\u04FF][\w\u0400-\u04FF-]*\s*\(([^()]*)\)")
_TAB_MENTION = re.compile(r"\b(?:табл\.|таблиц\w*|tables?)\s*(\d+)", re.IGNORECASE)
_FIG_MENTION = re.compile(r"\b(?:рис\.|рисун\w*|fig\.|figures?)\s*(\d+)", re.IGNORECASE)
# A range/enumeration continuation directly after a mention: «табл. 2–4», «рисунки 2 и 3».
# A bare «и» cannot hijack «или» — the digit demanded right after the separator fails.
_MENTION_CHAIN = re.compile(r"\s*(?:[и,]|and\b|–|—|-)\s*(\d+)", re.IGNORECASE)
_HEADING_STYLE = re.compile(r"^Heading([1-6])$")


def _gloss_spans(text: str) -> list[tuple[int, int]]:
    """Spans of parenthesized Latin codes decoded by the Cyrillic word before «(» —
    «видимые (visible)», multi-code groups «(visible, faint)» included."""
    return [(m.start(1), m.end(1)) for m in _GLOSS.finditer(text)]


def _mention_chain(text: str, m: re.Match) -> list[tuple[int, str]]:
    """The matched number plus a short range/enumeration continuation after it.
    A dash range («табл. 2–4») covers every number inside it; an enumeration
    («рисунки 2 и 3») covers the named ones — each covered number carries the whole
    covered fragment as its matched text. The chain stops at anything that is not
    separator+number («2 по 5», «2 или 3»); a dash range wider than 20 contributes
    its endpoints only."""
    out = [(int(m.group(1)), m.group(0))]
    tail = text[m.end():m.end() + 20]
    pos = 0
    while (cm := _MENTION_CHAIN.match(tail, pos)) is not None:
        fragment = m.group(0) + tail[pos:cm.end()]
        n = int(cm.group(1))
        sep = tail[pos:cm.start(1)].strip()
        prev = out[-1][0]
        if sep in {"–", "—", "-"} and 0 < n - prev <= 20:
            out.extend((k, fragment) for k in range(prev + 1, n))
        out.append((n, fragment))
        pos = cm.end()
    return out


def _vertical_checks(units: list[TextUnit], file: str,
                     lines: list[tuple[str, bool]]) -> list[dict]:
    """Sequence/ref-target/heading findings — same shape as the regex ones, all warn.

    Silent when the material is absent: a .docx without «Таблица N» captions,
    «табл. N» mentions and Heading styles produces no findings. `ref` of a caption or
    a mention is the unit it sits in ("" for body paragraphs); the qmd hint comes from
    the same `_hint` the regex findings use — one anchor, no double counting.
    """
    out: list[dict] = []

    def finding(u: TextUnit, id_: str, message: str, matched: str) -> None:
        f = asdict(Finding(file, u.lineno, 1, id_, "warn", message, matched))
        f["unit"] = u.ref
        f["qmd"] = _hint(lines, matched) if lines else ""
        out.append(f)

    caps: dict[str, list[tuple[int, TextUnit, str]]] = {"table": [], "figure": []}
    mentions: dict[str, list[tuple[TextUnit, int, str]]] = {"table": [], "figure": []}
    label = {"table": "Таблица", "figure": "Рисунок"}
    for u in units:
        cap = _CAPTION.match(u.text)
        if cap:
            kind = "figure" if cap.group(1).lower().startswith(("рис", "figure")) else "table"
            if not re.search(r"\((?:продолжени\w*|continued)\)", u.text, re.IGNORECASE):
                caps[kind].append((int(cap.group(2)), u, cap.group(0).strip()))
            continue
        for m in _TAB_MENTION.finditer(u.text):
            for n, matched in _mention_chain(u.text, m):
                mentions["table"].append((u, n, matched))
        for m in _FIG_MENTION.finditer(u.text):
            for n, matched in _mention_chain(u.text, m):
                mentions["figure"].append((u, n, matched))

    for kind, seq_id in (("table", "render-table-sequence"),
                         ("figure", "render-figure-sequence")):
        seen: set[int] = set()
        top = 0
        last: tuple[int, TextUnit, str] | None = None
        last_dup = False
        for n, u, matched in caps[kind]:
            last, last_dup = (n, u, matched), n in seen
            if n in seen:
                finding(u, seq_id, f"дубликат номера: «{label[kind]} {n}» уже был", matched)
            elif top == 0 and n != 1:
                finding(u, seq_id,
                        f"нумерация начинается не с 1: «{label[kind]} {n}»", matched)
            elif n > top + 1:
                finding(u, seq_id,
                        f"пропуск номера: после «{label[kind]} {top}» идёт «{label[kind]} {n}»",
                        matched)
            seen.add(n)
            top = max(top, n)
        # issue #100: a late out-of-order caption — 1, 3, 4, 2 — ends below the
        # running max with no duplicate to explain it: permutation-level disorder
        if last is not None and not last_dup and last[0] < top:
            finding(last[1], seq_id,
                    f"нарушение порядка нумерации: «{label[kind]} {last[0]}» стоит после "
                    f"«{label[kind]} {top}»", last[2])

    for kind in ("table", "figure"):
        cap_nums = {n for n, _u, _m in caps[kind]}
        mentioned = {n for _u, n, _t in mentions[kind]}
        for u, n, text in mentions[kind]:
            if n not in cap_nums:
                finding(u, "render-ref-target",
                        f"упоминание «{text.strip()}» — подписи «{label[kind]} {n}» в документе нет",
                        text.strip())
        for n, u, matched in caps[kind]:
            if n not in mentioned:
                finding(u, "render-ref-target",
                        f"подпись «{matched}» не упоминается в тексте («табл./рис. {n}»)",
                        matched)

    prev = 0
    for u in units:
        st = _HEADING_STYLE.match(u.style)
        if not st:
            continue
        level = int(st.group(1))
        if prev and level > prev + 1:
            finding(u, "render-heading-levels",
                    f"пропущен уровень заголовка: после Heading{prev} идёт Heading{level}",
                    u.text[:80])
        prev = level
    return out


def lint_render(path: Path, entries: list[dict], qmd: Path | None = None) -> list[dict]:
    """Regex entries + vertical checks over every unit; Finding fields + `unit` + `qmd`."""
    lines = _qmd_lines(qmd) if qmd else []
    out: list[dict] = []
    units = extract_units(path)
    for u in units:
        # issue #88: in captions and cells a Latin data code decoded by a Russian
        # term right beside it — «видимые (visible)» — is legal; bare codes are not
        glossed = (_gloss_spans(u.text)
                   if u.kind == "cell" or _CAPTION.match(u.text) else [])
        for e in entries:
            exc = e.get("except")
            if exc and exc.lower() in u.text.lower():
                continue
            for m in e["_rx"].finditer(u.text):
                if (e["id"] == "term-latin-data-code"
                        and any(s <= m.start() and m.end() <= t for s, t in glossed)):
                    continue
                f = Finding(str(path), u.lineno, m.start() + 1, e["id"],
                            e["severity"], e["message"], m.group(0))
                d = asdict(f)
                d["unit"] = u.ref
                d["qmd"] = _hint(lines, m.group(0)) if lines else ""
                out.append(d)
    out.extend(_vertical_checks(units, str(path), lines))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lint the rendered .docx (canon regex + vertical checks)")
    ap.add_argument("docx", help="rendered .docx")
    ap.add_argument("--qmd", help="source .qmd — attaches qmd:LINE hints to findings")
    ap.add_argument("--json", action="store_true", help="flat findings array on stdout")
    args = ap.parse_args(argv)
    try:
        if args.qmd:
            entries, _ = effective_entries(args.qmd)  # canon + the qmd project's overlay
        else:
            entries = load_entries(None)
    except ConfigError as e:
        print(f"config: {e}", file=sys.stderr)
        return 3
    try:
        findings = lint_render(Path(args.docx), entries,
                               Path(args.qmd) if args.qmd else None)
    except DocxError as e:
        print(e, file=sys.stderr)
        return 2
    except OSError as e:
        print(f"вход не читается — {e}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"config: {args.qmd}: исходник не в UTF-8 — пересохраните файл в UTF-8",
              file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(findings, ensure_ascii=False))
    else:
        for f in findings:
            anchor = f"{f['file']}:{f['line']}" + (f":{f['unit']}" if f["unit"] else "")
            print(f"{anchor}: [{f['severity']}] {f['id']}: {f['message']} ({f['matched']})")
            if f["qmd"]:
                print(f"  источник: {args.qmd}:{f['qmd']}")
    return 1 if any(f["severity"] == "error" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
