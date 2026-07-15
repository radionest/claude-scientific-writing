import json
import subprocess
from pathlib import Path

import pytest

from lib import lint_prose
from lib.lint_prose import ConfigError, load_raw, merge_entries
from lib.lint_prose import local_dict_path, main


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


@pytest.fixture(autouse=True)
def _clear_git_cache():
    lint_prose._GIT_ROOT_CACHE.clear()
    yield
    lint_prose._GIT_ROOT_CACHE.clear()


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def _write_local(root: Path, entries) -> Path:
    d = root / ".claude" / "scientific-writing"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "dictionary.json"
    p.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    return p


def _qmd(root: Path, text: str) -> Path:
    p = root / "doc.qmd"
    p.write_text(text, encoding="utf-8")
    return p


MASTER = {"id": "canon-master-model", "layer": "doc", "severity": "warn",
          "pattern": "модель печени", "message": "канон «мастер-модель»"}


def test_local_dict_path_in_repo(tmp_path):
    root = _git_repo(tmp_path)
    assert local_dict_path(root / "doc.qmd") == root / ".claude" / "scientific-writing" / "dictionary.json"


def test_local_dict_path_none_outside_repo(tmp_path):
    assert local_dict_path(tmp_path / "doc.qmd") is None


def test_local_rule_fires(tmp_path, capsys):
    root = _git_repo(tmp_path)
    _write_local(root, [MASTER])
    q = _qmd(root, "мы построили модель печени и отметили очаги\n")
    main([str(q), "--json"])
    assert "canon-master-model" in capsys.readouterr().out


def test_local_error_sets_exit_1(tmp_path):
    root = _git_repo(tmp_path)
    _write_local(root, [{**MASTER, "severity": "error"}])
    q = _qmd(root, "мы построили модель печени\n")
    assert main([str(q)]) == 1


def test_no_local_flag_ignores_dict(tmp_path, capsys):
    root = _git_repo(tmp_path)
    _write_local(root, [MASTER])
    q = _qmd(root, "мы построили модель печени\n")
    main([str(q), "--json", "--no-local"])
    assert "canon-master-model" not in capsys.readouterr().out


def test_local_dictionary_flag_forces_path(tmp_path, capsys):
    d = _write(tmp_path, [MASTER])  # tmp_path/dict.json, outside .claude/, no repo needed
    q = tmp_path / "doc.qmd"
    q.write_text("мы построили модель печени\n", encoding="utf-8")
    main([str(q), "--json", "--local-dictionary", str(d)])
    assert "canon-master-model" in capsys.readouterr().out


def test_override_tightens_pattern_removes_finding(tmp_path, capsys):
    root = _git_repo(tmp_path)
    _write_local(root, [{"id": "jargon-kogorta", "pattern": "когортищ",
                         "severity": "warn", "message": "m"}])
    q = _qmd(root, "пациенты когорты наблюдались\n")
    main([str(q), "--json"])
    assert "jargon-kogorta" not in capsys.readouterr().out


def test_no_repo_base_only_no_crash(tmp_path, capsys):
    _write_local(tmp_path, [MASTER])  # placed, but tmp_path is not a git repo -> ignored
    q = tmp_path / "doc.qmd"
    q.write_text("референсный стандарт применён\n", encoding="utf-8")
    rc = main([str(q), "--json"])
    out = capsys.readouterr().out
    assert rc == 1                          # base calque-referens (error) still fires
    assert "canon-master-model" not in out  # local ignored (no git root)


def test_malformed_local_returns_2_and_message(tmp_path, capsys):
    root = _git_repo(tmp_path)
    d = root / ".claude" / "scientific-writing"
    d.mkdir(parents=True)
    (d / "dictionary.json").write_text("{broken", encoding="utf-8")
    q = _qmd(root, "любой текст\n")
    rc = main([str(q)])
    assert rc == 2
    assert "ошибка локального словаря" in capsys.readouterr().err


def test_forced_missing_local_dictionary_errors(tmp_path, capsys):
    q = tmp_path / "doc.qmd"
    q.write_text("текст\n", encoding="utf-8")
    rc = main([str(q), "--local-dictionary", str(tmp_path / "nope.json")])
    assert rc == 2
    assert "ошибка локального словаря" in capsys.readouterr().err


def test_two_files_two_repos_each_gets_own_local(tmp_path, capsys):
    repo_a = _git_repo(tmp_path / "a")
    repo_b = _git_repo(tmp_path / "b")
    _write_local(repo_a, [{"id": "local-alpha", "layer": "doc", "pattern": "альфаметка",
                           "severity": "warn", "message": "a"}])
    _write_local(repo_b, [{"id": "local-beta", "layer": "doc", "pattern": "бетаметка",
                           "severity": "warn", "message": "b"}])
    doc_a = _qmd(repo_a, "здесь альфаметка и бетаметка присутствуют\n")
    doc_b = _qmd(repo_b, "здесь альфаметка и бетаметка присутствуют\n")
    main([str(doc_a), str(doc_b), "--json"])
    findings = json.loads(capsys.readouterr().out)
    ids_a = {f["id"] for f in findings if f["file"] == str(doc_a)}
    ids_b = {f["id"] for f in findings if f["file"] == str(doc_b)}
    assert "local-alpha" in ids_a and "local-beta" not in ids_a
    assert "local-beta" in ids_b and "local-alpha" not in ids_b


def test_load_raw_bad_severity(tmp_path):
    p = _write(tmp_path, [{"id": "x", "pattern": "a", "severity": "Error", "message": "m"}])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_non_string_except(tmp_path):
    p = _write(tmp_path, [{"id": "x", "pattern": "a", "severity": "warn", "message": "m",
                           "except": ["b", "c"]}])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_string_except_ok(tmp_path):
    p = _write(tmp_path, [{"id": "x", "pattern": "a", "severity": "warn", "message": "m",
                           "except": "b"}])
    assert load_raw(p)[0]["except"] == "b"
