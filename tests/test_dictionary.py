import json, re
from pathlib import Path

import pytest

from lib.lint_prose import lint_source, load_check_entries, load_entries
from lib.morph import Morph
from lib.qmd_prose import extract_prose

ROOT = Path(__file__).resolve().parents[1]
MORPH = Morph.load()


def _load():
    entries = []
    for name in ("dictionary.json", "orthography.json"):
        entries += json.loads((ROOT / "canon" / name).read_text(encoding="utf-8"))["entries"]
    return entries


def _lint_fixture(name: str):
    src = (ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8")
    return lint_source(src, load_entries(None), load_check_entries(), MORPH, file=name)


def test_entries_wellformed_and_unique():
    entries = _load()
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for e in entries:
        assert e["layer"] in {"universal", "genre:report", "genre:article", "genre:educational", "doc"}
        assert e["severity"] in {"error", "warn", "info"}
        assert e["message"].strip()
        if e.get("kind") == "check":
            assert "pattern" not in e, f"{e['id']}: у check-правила не должно быть pattern"
        else:
            re.compile(e["pattern"])  # must compile


def test_check_entries_are_registered():
    from lib import checks
    for e in _load():
        if e.get("kind") == "check":
            assert checks.get(e["id"]) is not None, f"{e['id']}: нет реализации в lib/checks"


def test_patterns_avoid_cyrillic_range_without_yo():
    """[а-я] исключает «ё» (U+0451): «отнес[а-я]+» не матчит «отнесённые». В хвостах — \\w."""
    for e in _load():
        if e.get("kind") == "check":
            continue
        assert "[а-я]" not in e["pattern"], f"{e['id']}: [а-я] не матчит «ё» — используй \\w"


@pytest.mark.parametrize("fixture", ["calques.qmd", "editor-review.qmd"])
def test_every_fixture_phrase_is_flagged(fixture):
    """The oracle runs the *whole* rule set — regex entries and code checks alike, so a
    fixture line whose rule lives in lib/checks still counts as covered.

    `editor-review.qmd` is a morphology-mode gate: its причастный/деепричастный lines are
    only reachable with the optional extra, and those checks correctly go silent without it.
    """
    if fixture == "editor-review.qmd" and not MORPH.available:
        pytest.skip("оракул орфографии требует опционального экстра morph")
    findings = _lint_fixture(fixture)
    flagged = {f.line for f in findings}
    src = (ROOT / "tests" / "fixtures" / fixture).read_text(encoding="utf-8")
    for pl in extract_prose(src):
        assert pl.lineno in flagged, f"{fixture}:{pl.lineno} не поймана: {pl.text.strip()!r}"


def test_good_examples_do_not_trip_their_own_rule():
    """Every entry carrying bad/good must flag the bad and leave the good alone —
    the false-positive gate the tune-rules design mandates."""
    from lib import checks as check_registry
    entries, checks_ = load_entries(None), load_check_entries()
    for e in _load():
        if not (e.get("bad") and e.get("good")):
            continue
        bad = {f.id for f in lint_source(e["bad"] + "\n", entries, checks_, MORPH)}
        good = {f.id for f in lint_source(e["good"] + "\n", entries, checks_, MORPH)}
        # Only a check that goes silent without the extra may skip the «bad» gate. The
        # token-level ones (`doc-*`, `ortho-hyphen-linebreak`, fronted-adverbial) still
        # fire in degraded mode, so keying on `kind == "check"` left them unverified.
        if MORPH.available or not check_registry.needs_morph(e["id"]):
            assert e["id"] in bad, f"{e['id']}: не ловит собственный пример «bad»"
        assert e["id"] not in good, f"{e['id']}: срабатывает на собственном примере «good»"
