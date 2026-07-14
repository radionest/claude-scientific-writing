import json
from pathlib import Path

import pytest

from lib.lint_prose import ConfigError, load_raw


def _write(tmp_path: Path, entries) -> Path:
    p = tmp_path / "dict.json"
    p.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_raw_valid_compiles_rx(tmp_path):
    p = _write(tmp_path, [{"id": "x", "pattern": "abc", "severity": "warn", "message": "m"}])
    entries = load_raw(p)
    assert entries[0]["_rx"].search("xabcx")


def test_load_raw_bad_json(tmp_path):
    p = tmp_path / "dict.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_missing_entries_key(tmp_path):
    p = tmp_path / "dict.json"
    p.write_text(json.dumps({"rules": []}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_missing_required_field(tmp_path):
    p = _write(tmp_path, [{"id": "x", "severity": "warn", "message": "m"}])  # no pattern
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_duplicate_id(tmp_path):
    p = _write(tmp_path, [
        {"id": "x", "pattern": "a", "severity": "warn", "message": "m"},
        {"id": "x", "pattern": "b", "severity": "warn", "message": "m"},
    ])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_bad_regex(tmp_path):
    p = _write(tmp_path, [{"id": "x", "pattern": "(", "severity": "warn", "message": "m"}])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_disabled_needs_only_id(tmp_path):
    p = _write(tmp_path, [{"id": "jargon-kogorta", "disabled": True}])
    entries = load_raw(p)
    assert entries[0]["id"] == "jargon-kogorta"
    assert "_rx" not in entries[0]


def test_load_raw_non_dict_entry(tmp_path):
    p = _write(tmp_path, ["not-an-object"])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_non_string_pattern(tmp_path):
    p = _write(tmp_path, [{"id": "x", "pattern": ["a", "b"], "severity": "warn", "message": "m"}])
    with pytest.raises(ConfigError):
        load_raw(p)
