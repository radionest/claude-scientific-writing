"""Prose-level diff + FN/FP triage between a pristine and an edited .qmd. Stdlib only."""
from __future__ import annotations
import argparse, json, sys
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path

from lib.lint_prose import ConfigError, Finding, effective_entries, lint_source
from lib.morph import Morph
from lib.qmd_prose import extract_prose


@dataclass
class Hunk:
    line: int            # 1-based line in the edited file (or pristine for pure deletions)
    before: str
    after: str
    triage: str          # "FN" | "FP" | "neutral"
    rule_hit: str | None
    before_dirty: bool


def _hits_by_line(findings: list[Finding]) -> dict[int, list[str]]:
    """Rule ids per source line, in discovery order.

    `info` severity stays out: `ortho-spelling` fires on live terminology and an advisory
    hit is not "already caught" — the same call `docx_review.triage` makes.
    """
    hits: dict[int, list[str]] = {}
    for f in findings:
        if f.severity == "info":
            continue
        hits.setdefault(f.line, []).append(f.id)
    return hits


def _first_hit(lines: list[int], hits: dict[int, list[str]]) -> str | None:
    """First rule id on any of the hunk's prose lines, else None."""
    for ln in lines:
        if hits.get(ln):
            return hits[ln][0]
    return None


def _prose(src: str):
    pls = extract_prose(src)
    return [pl.text.strip() for pl in pls], [pl.lineno for pl in pls]


def diff_prose(pristine_src: str, edited_src: str, entries: list[dict],
               check_entries: list[dict] | None = None,
               morph: Morph | None = None) -> list[Hunk]:
    """Diff the prose of two documents and triage each hunk against the effective rule set.

    `lint_source` runs once per side over the whole document, not per hunk: check-kind
    rules see the real document (`doc-*` consistency checks compare variants across it),
    and a hunk is covered when a finding lands on any of its prose lines. Morph.load() is
    fine here — this is a dev tool, not the hook.
    """
    m = morph or Morph.load()
    b_hits = _hits_by_line(lint_source(pristine_src, entries, check_entries or [], m))
    a_hits = _hits_by_line(lint_source(edited_src, entries, check_entries or [], m))
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
        after_hit = _first_hit(a_line[j1:j2], a_hits)
        before_hit = _first_hit(b_line[i1:i2], b_hits)
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
    try:
        entries, checks = effective_entries(args.edited, args.dictionary)
    except ConfigError as e:
        print(f"tune_diff: ошибка локального словаря {e}", file=sys.stderr)
        return 3
    pristine_src = Path(args.pristine).read_text(encoding="utf-8")
    edited_src = Path(args.edited).read_text(encoding="utf-8")
    hunks = diff_prose(pristine_src, edited_src, entries, checks)
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
