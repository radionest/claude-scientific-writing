import json
from pathlib import Path

import pytest

from lib.lint_prose import ConfigError, load_raw, merge_entries


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


def test_load_raw_invalid_utf8(tmp_path):
    p = tmp_path / "dict.json"
    p.write_bytes(b"\xff\xfe{bad}")
    with pytest.raises(ConfigError):
        load_raw(p)


def _base():
    return [
        {"id": "calque-referens", "pattern": "референс", "severity": "error", "message": "m"},
        {"id": "jargon-kogorta", "pattern": "когорт", "severity": "warn", "message": "m"},
    ]


def test_merge_adds_new_id():
    merged = merge_entries(_base(), [{"id": "canon-master-model", "pattern": "модель печени",
                                      "severity": "warn", "message": "m"}])
    assert [e["id"] for e in merged] == ["calque-referens", "jargon-kogorta", "canon-master-model"]


def test_merge_override_replaces_by_id():
    merged = merge_entries(_base(), [{"id": "jargon-kogorta", "pattern": "когорт",
                                      "severity": "error", "message": "m2"}])
    kog = [e for e in merged if e["id"] == "jargon-kogorta"][0]
    assert kog["severity"] == "error" and kog["message"] == "m2"
    assert len(merged) == 2  # replaced in place, not appended


def test_merge_disabled_drops_base_rule():
    merged = merge_entries(_base(), [{"id": "jargon-kogorta", "disabled": True}])
    assert [e["id"] for e in merged] == ["calque-referens"]


def test_merge_disabled_absent_is_noop():
    merged = merge_entries(_base(), [{"id": "no-such-rule", "disabled": True}])
    assert [e["id"] for e in merged] == ["calque-referens", "jargon-kogorta"]


def test_merge_preserves_base_order_then_new():
    merged = merge_entries(_base(), [
        {"id": "zzz-new", "pattern": "z", "severity": "warn", "message": "m"},
        {"id": "calque-referens", "pattern": "референс", "severity": "warn", "message": "m"},
    ])
    assert [e["id"] for e in merged] == ["calque-referens", "jargon-kogorta", "zzz-new"]
