"""Editor .docx review → the triage shape `lib.tune_diff` produces. Stdlib only.

An editor's review is the highest-quality calibration signal available: every comment is a
defect a human found that the rules did not. This reads the comments straight out of the
OOXML parts, keeping exact character offsets — which is why it does not go through pandoc
markdown like `~/.claude/scripts/docx_review.py` does.

    python3 -m lib.docx_review review.docx --json

Each item is `{line, before, after, triage, rule_hit, comment}`:
- `before` — the anchored text with context;
- `after`  — the editor's replacement when they tracked a change, else "";
- `triage` — "FN" when no rule fires on the anchor (a rule is missing — the signal to
  learn from), "covered" when one already does;
- `rule_hit` — the rule id when covered.
"""
from __future__ import annotations
import argparse, json, sys, zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from xml.etree import ElementTree as ET

from lib.lint_prose import lint_source, load_check_entries, load_entries
from lib.morph import Morph

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CONTEXT = 140


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
    sentence: str = ""  # the sentence it sits in — what triage is decided on
    anchor_at: int = 0  # anchor offset within `sentence`


class DocxError(Exception):
    """Not a readable .docx."""


def extract(path: Path, context: int = _CONTEXT) -> list[ReviewItem]:
    try:
        with zipfile.ZipFile(path) as z:
            return _extract(z, context)
    except zipfile.BadZipFile as e:
        raise DocxError(f"{path}: не .docx (не zip-архив)") from e
    except KeyError as e:
        raise DocxError(f"{path}: в архиве нет части {e} — файл повреждён или это не .docx") from e


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


def triage(items: list[ReviewItem], morph: Morph | None = None) -> list[ReviewItem]:
    """Mark items the current rule set already catches, so tuning only sees real misses.

    A rule counts as covering a comment only when it fires *on the anchor* — the sentence
    is linted, but a finding elsewhere in it is a different defect that happens to share a
    sentence, which is exactly how the old dictionary looked like it covered this review
    when it covered none of it.
    """
    entries, checks = load_entries(None), load_check_entries()
    m = morph or Morph.load()
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
            hit = f.id
            break
        out.append(ReviewItem(**{**asdict(it),
                                 "triage": "covered" if hit else "FN", "rule_hit": hit}))
    return out


def _sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = max(text.rfind(c, 0, start) for c in ".!?\n")
    right_candidates = [p for p in (text.find(c, end) for c in ".!?\n") if p != -1]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return (left + 1 if left != -1 else 0), right


def _norm(s: str) -> str:
    return " ".join(s.split())


def _as_int(v: str) -> int:
    try:
        return int(v)
    except ValueError:
        return 0


def _comments(z: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, str]]:
    try:
        root = ET.fromstring(z.read("word/comments.xml"))
    except KeyError:
        return {}, {}
    bodies, authors = {}, {}
    for c in root.iter(_W + "comment"):
        cid = c.get(_W + "id") or ""
        bodies[cid] = "".join(t.text or "" for t in c.iter(_W + "t")).strip()
        authors[cid] = c.get(_W + "author") or ""
    return bodies, authors


def _document(z: zipfile.ZipFile):
    """Flatten the body to text, recording comment-range offsets and paragraph starts."""
    root = ET.fromstring(z.read("word/document.xml"))
    parts: list[str] = []
    pos = 0
    starts: dict[str, int] = {}
    ends: dict[str, int] = {}
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
    root = ET.fromstring(z.read("word/document.xml"))
    items: list[ReviewItem] = []
    for para_no, p in enumerate(root.iter(_W + "p"), start=1):
        ins = "".join(t.text or "" for node in p.iter(_W + "ins") for t in node.iter(_W + "t"))
        dele = "".join(t.text or "" for node in p.iter(_W + "del")
                       for t in node.iter(_W + "delText"))
        if not ins and not dele:
            continue
        items.append(ReviewItem(line=para_no, before=" ".join(dele.split()),
                                after=" ".join(ins.split()), triage="FN", rule_hit=None,
                                comment="(tracked change)",
                                author=p.get(_W + "author") or ""))
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
        items = triage(extract(path, args.context))
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
