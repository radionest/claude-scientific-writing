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
exact miss falls back to the literal prefix before the first `{`. Advisory by
design: exit 1 on error-severity findings, but no hook gates on it.

Regex application duplicates `lint_text`'s inner loop instead of reusing it:
`lint_text` routes through `extract_prose`, whose markdown filtering (tables,
fences) would drop the very lines this module exists to lint.
"""
from __future__ import annotations
import argparse, json, sys, xml.parsers.expat, zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from lib.docx_review import DocxError, _OLE_MAGIC, _parse_xml
from lib.lint_prose import ConfigError, Finding, effective_entries, load_entries

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class TextUnit:
    lineno: int  # document-wide paragraph ordinal — a .docx has no qmd line numbers
    kind: str    # "body" | "cell"
    ref: str     # "" for body, "tbl2 r1 c3" for a table cell
    text: str


def _para_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(_W + "t"))


def extract_units(path: Path) -> list[TextUnit]:
    """Body paragraphs + one unit per table cell, in document order.

    A cell unit flattens every paragraph inside the cell (nested tables included)
    into one space-joined text — a cell is one linting unit, not many lines.
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
    except KeyError as e:
        raise DocxError(f"{path}: в архиве нет части {e} — файл повреждён или это не .docx") from e
    except xml.parsers.expat.ExpatError as e:
        raise DocxError(f"{path}: повреждённый XML внутри .docx — {e}") from e
    except NotImplementedError as e:
        # zipfile raises it on unsupported compression, not on a password
        raise DocxError(f"{path}: неподдерживаемый метод сжатия внутри архива — {e}") from e
    except RuntimeError as e:
        raise DocxError(f"{path}: файл защищён паролем — расшифруйте его и повторите") from e

    units: list[TextUnit] = []
    n = 0        # document-wide paragraph ordinal
    tbl_no = 0
    body = root.find(_W + "body")
    for el in body if body is not None else ():
        if el.tag == _W + "p":
            n += 1
            units.append(TextUnit(n, "body", "", _para_text(el)))
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
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        out.append((line, in_fence))
    return out


def _hint(lines: list[tuple[str, bool]], matched: str) -> str:
    """`L12` / `L12 (chunk)` / "". Exact substring first; else the literal prefix
    before the first `{` with the rendered numeric value stripped (digits,
    percent, brackets, dot, comma) — dash/colon separators stay as the anchor,
    >= 4 chars."""
    probes = [matched, matched.split("{", 1)[0].rstrip(" 0123456789%().,")]
    for probe in probes:
        if len(probe) < 4:
            continue
        for lineno, (text, in_chunk) in enumerate(lines, 1):
            if probe in text:
                return f"L{lineno}" + (" (chunk)" if in_chunk else "")
    return ""


def lint_render(path: Path, entries: list[dict], qmd: Path | None = None) -> list[dict]:
    """Regex entries over every unit; Finding fields + `unit` + `qmd` per finding."""
    lines = _qmd_lines(qmd) if qmd else []
    out: list[dict] = []
    for u in extract_units(path):
        for e in entries:
            exc = e.get("except")
            if exc and exc.lower() in u.text.lower():
                continue
            for m in e["_rx"].finditer(u.text):
                f = Finding(str(path), u.lineno, m.start() + 1, e["id"],
                            e["severity"], e["message"], m.group(0))
                d = asdict(f)
                d["unit"] = u.ref
                d["qmd"] = _hint(lines, m.group(0)) if lines else ""
                out.append(d)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lint the rendered .docx (regex canon rules)")
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
