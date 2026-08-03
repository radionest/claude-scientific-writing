import json, re
from pathlib import Path
from lib.qmd_prose import extract_prose

ROOT = Path(__file__).resolve().parents[1]


def _load():
    return json.loads((ROOT / "canon" / "dictionary.json").read_text(encoding="utf-8"))["entries"]


def test_entries_wellformed_and_unique():
    entries = _load()
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for e in entries:
        assert e["layer"] in {"universal", "genre:report", "genre:article", "genre:educational", "doc"}
        assert e["severity"] in {"error", "warn", "info"}
        re.compile(e["pattern"])  # must compile
        assert e["message"].strip()


def test_patterns_avoid_cyrillic_range_without_yo():
    """[а-я] исключает «ё» (U+0451): «отнес[а-я]+» не матчит «отнесённые». В хвостах — \\w."""
    for e in _load():
        assert "[а-я]" not in e["pattern"], f"{e['id']}: [а-я] не матчит «ё» — используй \\w"


def test_every_fixture_phrase_is_flagged():
    entries = _load()
    pats = [(e["id"], re.compile(e["pattern"], re.IGNORECASE | re.UNICODE)) for e in entries]
    src = (ROOT / "tests" / "fixtures" / "calques.qmd").read_text(encoding="utf-8")
    for pl in extract_prose(src):
        hit = any(p.search(pl.text) for _id, p in pats)
        assert hit, f"no dictionary entry flags: {pl.text.strip()!r}"
