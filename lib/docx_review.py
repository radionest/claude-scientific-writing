"""Editor .docx review → the triage shape `lib.tune_diff` produces. Stdlib only.

An editor's review is the highest-quality calibration signal available: every comment is a
defect a human found that the rules did not. This reads the comments straight out of the
OOXML parts, keeping exact character offsets, and anchors a comment stored as a bare
`w:commentReference` without a range at that mark. It never goes through pandoc markdown:
the importer's report generator (`~/.zcode/scripts/docx_review.py`) lost a heading-anchored
comment (#22) and 7 of 28 on a later live review while parsing comments from pandoc output.

    python3 -m lib.docx_review review.docx --json

Each item is `{line, before, after, triage, rule_hit, comment}`:
- `before` — the anchored text with context;
- `after`  — the editor's replacement when they tracked a change, else "";
- `triage` — "FN" when no rule fires on the anchor (a rule is missing — the signal to
  learn from), "covered" when one already does;
- `rule_hit` — the rule id when covered.
"""
from __future__ import annotations
import argparse, json, sys, xml.parsers.expat, zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from xml.etree import ElementTree as ET

from lib.document import _is_abbreviation
from lib.lint_prose import ConfigError, degraded_note, effective_entries, lint_source
from lib.morph import Morph

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CONTEXT = 140
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc / encrypted DOCX container


@dataclass
class ReviewItem:
    line: int  # paragraph ordinal — a .docx has no .qmd line numbers
    before: str
    after: str
    triage: str
    rule_hit: str | None
    comment: str
    author: str
    anchor: str = ""  # exactly what the editor selected
    sentence: str = ""  # the sentence it sits in (its paragraph for a trailing reference) — what triage is decided on
    anchor_at: int = 0  # anchor offset within `sentence`


class DocxError(Exception):
    """Not a readable .docx."""


def _parse_xml(data: bytes) -> ET.Element:
    """Parse an OOXML part, refusing any DTD.

    A `.docx` part never carries a DOCTYPE, while `ET.fromstring` happily expands internal
    entities — so a hostile file can exhaust memory («billion laughs»). Driving expat
    directly is what lets the DTD be refused: the C `XMLParser` does not expose its expat
    handlers, and `defusedxml` is a dependency this module cannot take — it is stdlib-only
    so the plugin hook can run under the system interpreter.

    `namespace_separator="}"` makes expat emit `uri}local`, one `{` short of the Clark
    notation the `_W + "tag"` lookups below use.
    """
    builder = ET.TreeBuilder()
    parser = xml.parsers.expat.ParserCreate(namespace_separator="}")
    parser.buffer_text = True

    def forbid_dtd(*_args: object) -> None:
        raise DocxError("XML-часть содержит DTD — файл отклонён")

    def clark(name: str) -> str:
        return "{" + name if "}" in name else name

    parser.StartDoctypeDeclHandler = forbid_dtd
    parser.StartElementHandler = lambda tag, attrs: builder.start(
        clark(tag), {clark(k): v for k, v in attrs.items()})
    parser.EndElementHandler = lambda tag: builder.end(clark(tag))
    parser.CharacterDataHandler = builder.data
    parser.Parse(data, True)
    return builder.close()


def extract(path: Path, context: int = _CONTEXT) -> list[ReviewItem]:
    with path.open("rb") as fh:
        if fh.read(len(_OLE_MAGIC)) == _OLE_MAGIC:
            raise DocxError(f"{path}: устаревший .doc или зашифрованный DOCX (OLE-контейнер) — "
                            "пересохраните как .docx без пароля")
    try:
        with zipfile.ZipFile(path) as z:
            return _extract(z, context)
    except zipfile.BadZipFile as e:
        raise DocxError(f"{path}: не .docx (не zip-архив)") from e
    except KeyError as e:
        raise DocxError(f"{path}: в архиве нет части {e} — файл повреждён или это не .docx") from e
    except xml.parsers.expat.ExpatError as e:
        raise DocxError(f"{path}: повреждённый XML внутри .docx — {e}") from e
    except NotImplementedError as e:
        # подкласс RuntimeError: zipfile бросает его на неподдерживаемом сжатии, не на пароле
        raise DocxError(f"{path}: неподдерживаемый метод сжатия внутри архива — {e}") from e
    except RuntimeError as e:
        raise DocxError(f"{path}: файл защищён паролем — расшифруйте его и повторите") from e


def _extract(z: zipfile.ZipFile, context: int) -> list[ReviewItem]:
    comments, authors = _comments(z)
    text, spans, para_at = _document(z)
    items: list[ReviewItem] = []
    for cid, body in sorted(comments.items(), key=lambda kv: _as_int(kv[0])):
        span = spans.get(cid)
        if span is None:
            continue
        start, end = span
        before = text[max(0, start - context):min(len(text), end + context)]
        sent_start, sent_end = _sentence_bounds(text, start, end)
        if not text[sent_start:sent_end].strip():
            # A reference after the paragraph's last period has no sentence of its own. Left
            # empty, `triage` would drop the ±25 window and judge the whole context instead.
            sent_start = text.rfind("\n", 0, start) + 1
            sent_end = text.find("\n", end)
            sent_end = len(text) if sent_end < 0 else sent_end
        sentence = _norm(text[sent_start:sent_end])
        anchor = _norm(text[start:end])
        # Offsets must be taken in normalised space: a prefix ending in whitespace loses a
        # character to `split()`, so measuring the prefix alone lands one short.
        anchor_at = max(0, len(_norm(text[sent_start:end])) - len(anchor))
        items.append(ReviewItem(line=para_at(start), before=_norm(before),
                                after="", triage="FN", rule_hit=None,
                                comment=body, author=authors.get(cid, ""),
                                anchor=anchor, sentence=sentence, anchor_at=anchor_at))
    items += _tracked_changes(text, z)
    return items


_NEAR = 25  # chars either side of the anchor a finding may land and still count


def triage(items: list[ReviewItem], rules: tuple[list[dict], list[dict]],
           morph: Morph) -> list[ReviewItem]:
    """Mark items the current rule set already catches, so tuning only sees real misses.

    A rule counts as covering a comment only when it fires *on the anchor* — the sentence
    is linted, but a finding elsewhere in it is a different defect that happens to share a
    sentence, which is exactly how the old dictionary looked like it covered this review
    when it covered none of it.

    `rules` and `morph` are required, computed by the caller: triage must see exactly what
    the gate enforces — a canon-only fallback would score anchors against disabled or
    allow-listed rules and mask real editor findings as «covered» (#55). `main` needs the
    same check entries and analyzer for the degraded-morphology note, so both cross one
    boundary instead of being derived twice.
    """
    entries, checks = rules
    m = morph
    out = []
    for it in items:
        probe = it.sentence or it.before or it.after
        lo = it.anchor_at - _NEAR
        hi = it.anchor_at + len(it.anchor) + _NEAR
        hit = None
        for f in lint_source(probe + "\n", entries, checks, m):
            if f.severity == "info":
                continue  # `ortho-spelling` fires on live terminology; it is not coverage
            if it.sentence and not (lo <= f.col - 1 <= hi):
                continue
            if not it.sentence and it.comment != "(tracked change)":
                break  # a comment with no sentence and no paragraph has nothing to be near
            hit = f.id
            break
        out.append(ReviewItem(**{**asdict(it),
                                 "triage": "covered" if hit else "FN", "rule_hit": hit}))
    return out


_SENT_CHARS = ".!?…\n"
_ABBR_WINDOW = 40  # all the left context `_is_abbreviation` needs to read the last word


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """Bounds of the sentence holding `[start, end)`.

    A period is a boundary only when `lib.document._is_abbreviation` says it is not part of
    «т.е.», «др.» or an initial — the same guard `split_sentences` applies. `triage` feeds
    this slice straight to `lint_source` to decide covered vs FN, so a sentence truncated
    at an abbreviation flips that verdict.
    """
    def breaks_at(i: int) -> bool:
        if text[i] not in _SENT_CHARS:
            return False
        return text[i] != "." or not _is_abbreviation(text[max(0, i - _ABBR_WINDOW):i])

    left = next((i for i in range(start - 1, -1, -1) if breaks_at(i)), -1)
    right = next((i + 1 for i in range(end, len(text)) if breaks_at(i)), len(text))
    return left + 1, right


def _norm(s: str) -> str:
    return " ".join(s.split())


def _as_int(v: str) -> int:
    try:
        return int(v)
    except ValueError:
        return 0


def _comments(z: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, str]]:
    try:
        root = _parse_xml(z.read("word/comments.xml"))
    except KeyError:
        return {}, {}
    bodies, authors = {}, {}
    for c in root.iter(_W + "comment"):
        cid = c.get(_W + "id") or ""
        bodies[cid] = "".join(t.text or "" for t in c.iter(_W + "t")).strip()
        authors[cid] = c.get(_W + "author") or ""
    return bodies, authors


def _document(z: zipfile.ZipFile):
    """Flatten the body to text, recording comment-range and reference offsets and paragraph starts."""
    root = _parse_xml(z.read("word/document.xml"))
    parts: list[str] = []
    pos = 0
    starts: dict[str, int] = {}
    ends: dict[str, int] = {}
    refs: dict[str, int] = {}
    para_starts: list[int] = [0]

    def walk(el) -> None:
        nonlocal pos
        for ch in el:
            tag = ch.tag
            if tag == _W + "p":
                walk(ch)
                parts.append("\n")
                pos += 1
                para_starts.append(pos)
            elif tag == _W + "commentRangeStart":
                starts[ch.get(_W + "id") or ""] = pos
            elif tag == _W + "commentRangeEnd":
                ends[ch.get(_W + "id") or ""] = pos
            elif tag == _W + "commentReference":
                refs[ch.get(_W + "id") or ""] = pos
            elif tag == _W + "t":
                s = ch.text or ""
                parts.append(s)
                pos += len(s)
            elif tag == _W + "tab":
                parts.append("\t")
                pos += 1
            else:
                walk(ch)

    walk(root)
    text = "".join(parts)
    spans = {cid: (s, ends.get(cid, s)) for cid, s in starts.items()}
    # A comment may carry its reference mark without any range: anchor it there.
    for cid, ref_at in refs.items():
        spans.setdefault(cid, (ref_at, ref_at))

    def para_at(offset: int) -> int:
        lo, hi = 0, len(para_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if para_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    return text, spans, para_at


def _tracked_changes(text: str, z: zipfile.ZipFile) -> list[ReviewItem]:
    """w:ins / w:del pairs, when the editor tracked changes instead of commenting."""
    root = _parse_xml(z.read("word/document.xml"))
    items: list[ReviewItem] = []
    for para_no, p in enumerate(root.iter(_W + "p"), start=1):
        ins = "".join(t.text or "" for node in p.iter(_W + "ins") for t in node.iter(_W + "t"))
        dele = "".join(t.text or "" for node in p.iter(_W + "del")
                       for t in node.iter(_W + "delText"))
        if not ins and not dele:
            continue
        # OOXML puts w:author on <w:ins>/<w:del>, never on the <w:p> that holds them.
        author = next((a for node in (*p.iter(_W + "ins"), *p.iter(_W + "del"))
                       for a in [node.get(_W + "author") or ""] if a), "")
        items.append(ReviewItem(line=para_no, before=" ".join(dele.split()),
                                after=" ".join(ins.split()), triage="FN", rule_hit=None,
                                comment="(tracked change)",
                                author=author))
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Editor .docx review → rule-tuning triage")
    ap.add_argument("docx")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--context", type=int, default=_CONTEXT)
    ap.add_argument("--only-missed", action="store_true",
                    help="drop items an existing rule already catches")
    args = ap.parse_args(argv)
    path = Path(args.docx)
    if not path.exists():
        print(f"docx_review: файл не найден: {path}", file=sys.stderr)
        return 2
    try:
        rules = effective_entries(path)
        doc_items = extract(path, args.context)
        # Morph after extract: refused files (OLE .doc, password, broken zip) never reach
        # the degraded note, so they must not pay for the analyzer construction either.
        morph = Morph.load()
        items = triage(doc_items, rules=rules, morph=morph)
    except ConfigError as e:
        print(f"docx_review: ошибка локального словаря {e}", file=sys.stderr)
        return 3
    except (DocxError, OSError) as e:
        print(f"docx_review: {e}", file=sys.stderr)
        return 2
    if args.only_missed:
        items = [i for i in items if i.triage == "FN"]
    if args.json:
        print(json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2))
    else:
        covered = sum(1 for i in items if i.triage == "covered")
        print(f"замечаний: {len(items)}   уже ловится правилами: {covered}   "
              f"промахов (FN): {len(items) - covered}")
        for i in items:
            if i.triage == "FN":
                print(f"  ¶{i.line} «{i.comment[:48]}» ← {i.before[:90]}")
    if not morph.available:
        # stderr, so the stdout contract (JSON/text summary) stays parseable, as in
        # tune_diff.main — under system python3 the FN/covered verdicts lose precision.
        print(degraded_note(rules[1], tool="docx_review"), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
