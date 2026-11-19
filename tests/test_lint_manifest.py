"""Eval manifest: the quality oracle above the per-fixture presence checks.

Layers, from inner to outer:
- `tests/fixtures/*.qmd` — a finding must appear on each defective line;
- canon `bad`/`good` — the rule flags its own bad and leaves its good alone;
- this module — every rule is *registered* (id + pinned severity + rationale) and the
  two eval documents reproduce their frozen finding profiles exactly.

A canon change that shifts any of that fails here on purpose: the baseline update must
be a conscious manifest edit, not a silent drift.
"""
import json
from collections import Counter
from pathlib import Path

import pytest

from lib import checks as check_registry
from lib.lint_prose import lint_source, load_check_entries, load_entries
from lib.morph import Morph

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "tests" / "eval"
MORPH = Morph.load()

MANIFEST = json.loads((EVAL / "lint-manifest.json").read_text(encoding="utf-8"))
RULES = {r["id"]: r for r in MANIFEST["rules"]}
DOCS = MANIFEST["documents"]
CASES = json.loads((EVAL / "rewrite-cases.json").read_text(encoding="utf-8"))["cases"]
DIMENSIONS = {"negation", "quantifier", "modality", "denominator", "comparator",
              "null-result", "claim-support", "citation-key", "condition",
              "code-preserved", "voice", "style", "numbers", "terminology"}


def _canon() -> dict[str, dict]:
    entries: list[dict] = []
    for name in ("dictionary.json", "orthography.json"):
        entries += json.loads((ROOT / "canon" / name).read_text(encoding="utf-8"))["entries"]
    return {e["id"]: e for e in entries}


CANON = _canon()


def _lint(text: str) -> list:
    return lint_source(text, load_entries(None), load_check_entries(), MORPH)


def _effective_severity(entry: dict) -> str:
    if not MORPH.available and entry.get("severity_without_morph"):
        return entry["severity_without_morph"]
    return entry["severity"]


def _profile_comparable(rule_id: str) -> bool:
    """A rule stays exactly comparable without the morph extra only when it neither
    goes silent (`needs_morph`) nor demotes (`severity_without_morph`)."""
    if MORPH.available:
        return True
    entry = CANON.get(rule_id)
    if entry is None:
        return True
    if entry.get("kind") == "check" and check_registry.needs_morph(rule_id):
        return False
    return not entry.get("severity_without_morph")


def _doc_profile(name: str) -> Counter:
    src = (EVAL / name).read_text(encoding="utf-8")
    counts = Counter((f.id, f.severity) for f in _lint(src))
    return Counter({k: n for k, n in counts.items() if _profile_comparable(k[0])})


def _expected_profile(name: str) -> Counter:
    expected = Counter()
    for row in DOCS[name]["findings"]:
        if _profile_comparable(row["id"]):
            expected[(row["id"], row["severity"])] += row["count"]
    return expected


def test_manifest_registration_is_complete():
    """Every canon rule registered, nothing stale: adding a rule without a manifest
    entry (severity + rationale) fails here — the PR-1 registration gate."""
    assert set(RULES) == set(CANON), \
        f"не совпадают: {sorted(set(RULES) ^ set(CANON))}"
    for rid, rule in RULES.items():
        assert rule["severity"] == CANON[rid]["severity"], f"{rid}: severity разошёлся с каноном"
        assert rule["rationale"].strip(), f"{rid}: пустое обоснование"


@pytest.mark.parametrize("rid", sorted(RULES))
def test_bad_trips_the_rule_at_pinned_severity(rid):
    entry = CANON[rid]
    if entry.get("kind") == "check" and not MORPH.available and check_registry.needs_morph(rid):
        pytest.skip("правило молчит без экстра morph")
    findings = _lint(entry["bad"] + "\n")
    expected = _effective_severity(entry)
    hits = [f for f in findings if f.id == rid]
    assert hits, f"{rid}: не ловит собственный bad"
    assert any(f.severity == expected for f in hits), \
        f"{rid}: severity {hits[0].severity} != пиннингу {expected}"


@pytest.mark.parametrize("rid", sorted(RULES))
def test_good_stays_silent(rid):
    findings = _lint(CANON[rid]["good"] + "\n")
    assert rid not in {f.id for f in findings}, f"{rid}: срабатывает на собственном good"


def test_lint_good_document_profile():
    """Good corpus: zero errors (pinned by `max_errors`); the warn/info inventory is
    frozen — a new warning on good text is a false positive to account for, not noise."""
    profile = _doc_profile("lint-good.qmd")
    errors = sum(n for (_, sev), n in profile.items() if sev == "error")
    assert errors == DOCS["lint-good.qmd"].get("max_errors", 0), "хороший corpus не даёт error"
    assert profile == _expected_profile("lint-good.qmd")


def test_lint_bad_document_profile():
    """Bad corpus: the full finding profile is frozen — both a lost catch and a new
    unexpected rule hit shift it and must be a conscious manifest update."""
    assert _doc_profile("lint-bad.qmd") == _expected_profile("lint-bad.qmd")


def test_rewrite_cases_schema():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "повтор id"
    assert any(c["expect"] == "damage" for c in CASES)
    assert any(c["expect"] == "clean" for c in CASES)
    for c in CASES:
        assert set(c) == {"id", "dimension", "expect", "before", "after", "note"}
        assert c["dimension"] in DIMENSIONS, c["id"]
        assert c["expect"] in {"damage", "clean"}
        assert c["before"].strip() and c["after"].strip()
        assert c["before"] != c["after"], f"{c['id']}: пара не минимальная — стороны совпадают"
        assert c["note"].strip(), f"{c['id']}: нет пояснения"


def test_rewrite_cases_are_invisible_to_the_linter():
    """The gold set isolates *meaning* damage: no side of any pair raises the
    deterministic error gate — catching these is the semantic reviewer's job, which
    is exactly why token comparison can never certify fidelity."""
    for c in CASES:
        for side in ("before", "after"):
            errors = [f for f in _lint(c[side] + "\n") if f.severity == "error"]
            assert not errors, \
                f"{c['id']}/{side}: линтер видит {[(f.id, f.matched) for f in errors]}"
