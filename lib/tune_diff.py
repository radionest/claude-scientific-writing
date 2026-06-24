"""Prose-level diff + FN/FP triage between a pristine and an edited .qmd. Stdlib only."""
from __future__ import annotations
import argparse, json
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path

from lib.qmd_prose import extract_prose
from lib.lint_prose import load_entries


@dataclass
class Hunk:
    line: int            # 1-based line in the edited file (or pristine for pure deletions)
    before: str
    after: str
    triage: str          # "FN" | "FP" | "neutral"
    rule_hit: str | None
    before_dirty: bool


def _rule_hit(text: str, entries: list[dict]) -> str | None:
    """Id of the first dictionary rule matching `text` (honoring `except`), else None."""
    low = text.lower()
    for e in entries:
        exc = e.get("except")
        if exc and exc.lower() in low:
            continue
        if e["_rx"].search(text):
            return e["id"]
    return None


def _first_hit(lines: list[str], entries: list[dict]) -> str | None:
    """First rule id hitting any line (per-line, so `except` matches lib.lint_prose semantics)."""
    for ln in lines:
        h = _rule_hit(ln, entries)
        if h:
            return h
    return None


def _prose(src: str):
    pls = extract_prose(src)
    return [pl.text.strip() for pl in pls], [pl.lineno for pl in pls]


def diff_prose(pristine_src: str, edited_src: str, entries: list[dict]) -> list[Hunk]:
    b_text, b_line = _prose(pristine_src)
    a_text, a_line = _prose(edited_src)
    sm = SequenceMatcher(a=b_text, b=a_text, autojunk=False)
    hunks: list[Hunk] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        before = " ".join(b_text[i1:i2]).strip()
        after = " ".join(a_text[j1:j2]).strip()
        if not before and not after:
            continue
        after_hit = _first_hit(a_text[j1:j2], entries)
        before_hit = _first_hit(b_text[i1:i2], entries)
        if after_hit:
            triage = "FP"
        elif before and after:
            triage = "FN"
        else:
            triage = "neutral"
        line = a_line[j1] if j1 < len(a_line) else (b_line[i1] if i1 < len(b_line) else 0)
        hunks.append(Hunk(line=line, before=before, after=after, triage=triage,
                          rule_hit=after_hit, before_dirty=bool(before_hit)))
    return hunks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Prose diff + FN/FP triage for rule tuning")
    ap.add_argument("pristine")
    ap.add_argument("edited")
    ap.add_argument("--dictionary", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    entries = load_entries(args.dictionary)
    pristine_src = Path(args.pristine).read_text(encoding="utf-8")
    edited_src = Path(args.edited).read_text(encoding="utf-8")
    hunks = diff_prose(pristine_src, edited_src, entries)
    if args.json:
        print(json.dumps([asdict(h) for h in hunks], ensure_ascii=False, indent=2))
    else:
        for h in hunks:
            print(f"[{h.triage}] L{h.line} rule={h.rule_hit} before_dirty={h.before_dirty}")
            print(f"  - {h.before}")
            print(f"  + {h.after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
