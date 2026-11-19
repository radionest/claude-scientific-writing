"""Before/after artifact diff for scoped edits — the deterministic fidelity layer.

Compares two raw .qmd sources and reports added/removed/changed *artifacts*: numbers,
citation keys, crossrefs, code spans, URLs, frozen wordings. It never asserts semantic
equivalence — matching artifacts do not certify meaning (that is the fidelity
reviewer's judgment); every reported delta is a finding requiring an explicit
decision: restore, or allow with a stated reason.

Numbers are compared as a multiset of normalized keys (sign included, ranges split
into endpoints so «45–79» survives a rewrite as «от 45 до 79», Russian decimal comma,
thousands separators dropped, a trailing «%» bound to the number — both endpoints of
a range: «45–79 %» keys as «45%» and «79%»): a rephrase must keep every value with
its repetition count. Numbers inside protected spans (code, YAML, citations) are
masked out first — the code/citation deltas own those.
"""
from __future__ import annotations
import argparse
import difflib
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from lib.protected_spans import citation_keys, extract_spans

_PAIR_SIMILARITY = 0.5  # below this, removed+added stay separate findings

_NUM_RE = re.compile(
    r"(?<![\w.,])"
    r"(?P<left>[-+\u2212]?\d{1,3}(?:[ \u00A0\u202F]\d{3})*\d*(?:[.,]\d+)?)"
    r"(?:\s*[\u2013\u2014\u2212-]\s*(?P<right>\d{1,3}(?:[ \u00A0\u202F]\d{3})*\d*(?:[.,]\d+)?))?"
    r"(?P<pct>\s*%)?")


@dataclass(frozen=True, slots=True)
class GuardFinding:
    category: str  # number | citation-key | crossref | code | url | frozen
    action: str    # removed | added | changed
    key: str       # canonical artifact identity
    before: str
    after: str


def _numkey(raw: str, percent: bool) -> str:
    key = raw.replace(" ", "").replace("\u00A0", "").replace("\u202F", "")
    key = key.replace("\u2212", "-").replace(",", ".")
    return key + ("%" if percent else "")


def _masked(source: str) -> str:
    """Blank out all protected spans (offsets preserved) for number scanning."""
    chars = list(source)
    for s in extract_spans(source):
        for i in range(s.start, min(s.end, len(chars))):
            chars[i] = " "
    return "".join(chars)


def number_keys(source: str) -> Counter[str]:
    out: Counter[str] = Counter()
    for m in _NUM_RE.finditer(_masked(source)):
        # «45–79 %»: % belongs to the whole range — attach it to both endpoints
        # (conservative direction: no misses when one endpoint keeps its %)
        pct = bool(m.group("pct"))
        out[_numkey(m.group("left"), pct)] += 1
        if m.group("right"):
            out[_numkey(m.group("right"), pct)] += 1
    return out


def _pair_changed(category: str, removed: list[str], added: list[str],
                  out: list[GuardFinding]) -> None:
    """Merge a removed/added pair into one `changed` finding when similar enough."""
    while removed and added:
        ratio, r, a = max(
            (difflib.SequenceMatcher(None, r, a).ratio(), r, a)
            for r in removed for a in added)
        if ratio < _PAIR_SIMILARITY:
            break
        removed.remove(r)
        added.remove(a)
        out.append(GuardFinding(category, "changed", r, r, a))


def _delta(category: str, before_items: list[str],
           after_items: list[str]) -> list[GuardFinding]:
    b, a = Counter(before_items), Counter(after_items)
    removed = sorted((b - a).elements())
    added = sorted((a - b).elements())
    out: list[GuardFinding] = []
    _pair_changed(category, removed, added, out)
    out += [GuardFinding(category, "removed", r, r, "") for r in removed]
    out += [GuardFinding(category, "added", x, "", x) for x in added]
    return out


# protected-span category -> guard report category (citation spans report via keys)
_SPAN_REPORT = {"crossref": "crossref", "inline-python": "code",
                "inline-code": "code", "fenced-code": "code", "url": "url"}


def _frozen_findings(terms: list[str], before: str, after: str) -> list[GuardFinding]:
    out = []
    for term in terms:
        t = term.strip()
        if not t:
            continue
        b, a = before.count(t), after.count(t)
        if b != a:
            action = "changed" if b and a else ("removed" if b else "added")
            out.append(GuardFinding("frozen", action, t, str(b), str(a)))
    return out


def compare(before: str, after: str,
            frozen: list[str] | None = None) -> list[GuardFinding]:
    findings: list[GuardFinding] = []
    findings += _delta("number", list(number_keys(before).elements()),
                       list(number_keys(after).elements()))
    findings += _delta("citation-key", citation_keys(before), citation_keys(after))
    b_spans, a_spans = extract_spans(before), extract_spans(after)
    for span_category, report in _SPAN_REPORT.items():
        findings += _delta(
            report,
            [s.normalized for s in b_spans if s.category == span_category],
            [s.normalized for s in a_spans if s.category == span_category])
    findings += _frozen_findings(frozen or [], before, after)
    return sorted(findings, key=lambda f: (f.category, f.action, f.key))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Artifact diff between two .qmd revisions (advisory)")
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--frozen", default=None,
                    help="file of wordings that must survive verbatim, one per line")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    bpath, apath = Path(args.before), Path(args.after)
    if not bpath.is_file() or not apath.is_file():
        print(f"file not found: {bpath if not bpath.is_file() else apath}",
              file=sys.stderr)
        return 2
    frozen = None
    if args.frozen:
        fpath = Path(args.frozen)
        if not fpath.is_file():
            print(f"file not found: {fpath}", file=sys.stderr)
            return 2
        frozen = fpath.read_text(encoding="utf-8").splitlines()
    findings = compare(bpath.read_text(encoding="utf-8"),
                       apath.read_text(encoding="utf-8"), frozen)
    if args.json:
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    else:
        for f in findings:
            suffix = f"  {f.before!r} -> {f.after!r}" if f.action == "changed" else ""
            print(f"{f.action:8} {f.category:13} {f.key!r}{suffix}")
        print(
            f"{len(findings)} finding(s); each requires restore or an explicit "
            f"allowed reason — an empty diff means artifacts matched, not meaning "
            f"preserved", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
