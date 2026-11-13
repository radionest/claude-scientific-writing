import json
import subprocess
from pathlib import Path

import pytest

from lib import lint_prose
from lib.lint_prose import ConfigError, effective_entries, load_raw, merge_entries
from lib.lint_prose import local_dict_path, main


def _write(tmp_path: Path, entries) -> Path:
    p = tmp_path / "dict.json"
    p.write_text(json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    return p


def test_load_raw_valid_compiles_rx(tmp_path):
    p = _write(tmp_path, [{"id": "x", "layer": "doc", "pattern": "abc", "severity": "warn",
                           "message": "m"}])
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
    p = _write(tmp_path, [{"id": "x", "layer": "doc", "severity": "warn", "message": "m"}])  # no pattern
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
    p = _write(tmp_path, [{"id": "x", "layer": "doc", "pattern": "(", "severity": "warn",
                           "message": "m"}])
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
    p = _write(tmp_path, [{"id": "x", "layer": "doc", "pattern": ["a", "b"], "severity": "warn",
                           "message": "m"}])
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
    lint_prose._clear_caches()
    yield
    lint_prose._clear_caches()


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


def test_partial_override_of_a_check_inherits_severity_and_message(tmp_path, capsys):
    """The documented way to teach `ortho-spelling` a project's terms is an `allow` list and
    nothing else. Requiring severity/message there made the overlay raise ConfigError —
    a config-error exit — which blocks the very commit hook the overlay exists to satisfy."""
    root = _git_repo(tmp_path)
    _write_local(root, [{"id": "ortho-spelling", "allow": ["ремнант", "волюмометрия"]}])
    q = _qmd(root, "Волюмометрия ремнанта печени показала достаточный объём.\n")
    assert main([str(q), "--json"]) == 0
    ids = {f["id"] for f in json.loads(capsys.readouterr().out)}
    assert "ortho-spelling" not in ids


def test_partial_override_can_retune_severity_only(tmp_path, capsys):
    root = _git_repo(tmp_path)
    _write_local(root, [{"id": "jargon-kogorta", "severity": "error"}])
    q = _qmd(root, "пациенты когорты прошли обследование\n")
    assert main([str(q), "--json"]) == 1
    kog = [f for f in json.loads(capsys.readouterr().out) if f["id"] == "jargon-kogorta"]
    assert kog and kog[0]["severity"] == "error"
    assert "выборка" in kog[0]["message"], "message must be inherited from the base entry"


def test_effective_entries_overlay_end_to_end(tmp_path):
    """One overlay doing all four moves — retune, add, disable, allow — observed through
    the same (regex, check) split `effective_entries` hands to the linter."""
    root = _git_repo(tmp_path)
    _write_local(root, [
        {"id": "jargon-kogorta", "severity": "error"},
        MASTER,
        {"id": "calque-referens", "disabled": True},
        {"id": "ortho-spelling", "allow": ["ремнант"]},
    ])
    q = _qmd(root, "любой текст\n")
    entries, checks = effective_entries(q)
    by_id = {e["id"]: e for e in entries}
    assert "calque-referens" not in by_id
    kog = by_id["jargon-kogorta"]
    assert kog["severity"] == "error"
    assert kog["layer"] == "universal"
    assert "выборка" in kog["message"]
    assert by_id["canon-master-model"]["pattern"] == "модель печени"
    ortho = [e for e in checks if e["id"] == "ortho-spelling"][0]
    assert ortho["allow"] == ["ремнант"]
    assert ortho["severity"] == "info"


def test_local_dict_path_in_repo(tmp_path):
    root = _git_repo(tmp_path)
    assert local_dict_path(root / "doc.qmd") == root / ".claude" / "scientific-writing" / "dictionary.json"


def test_local_dict_path_none_outside_repo(tmp_path):
    assert local_dict_path(tmp_path / "doc.qmd") is None


MAIN_ONLY = {"id": "local-main-only", "layer": "doc", "pattern": "мейнметка",
             "severity": "warn", "message": "main-checkout rule"}
WT_OWN = {"id": "local-wt", "layer": "doc", "pattern": "веткаметка",
          "severity": "warn", "message": "worktree rule"}


def _git_commit(root: Path) -> None:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c",
                    "user.email=t@example.com", "commit", "-q", "-m", "init"], check=True)


def _add_worktree(root: Path, path: Path) -> Path:
    subprocess.run(["git", "-C", str(root), "worktree", "add", str(path)], check=True)
    return path


def test_local_dict_path_worktree_falls_back_to_main(tmp_path):
    root = _git_repo(tmp_path / "main")
    (root / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    _write_local(root, [MAIN_ONLY])  # gitignored: a linked worktree never checks it out
    _git_commit(root)
    wt = _add_worktree(root, tmp_path / "wt")
    assert local_dict_path(wt / "doc.qmd") == \
        root / ".claude" / "scientific-writing" / "dictionary.json"


def test_local_dict_path_main_checkout_named_dotgit(tmp_path):
    """The motivating case: a main checkout whose dir ends in `.git` — the old
    `--git-common-dir` + endswith("/.git") logic stripped it to the bogus sibling
    `project`, hiding the real overlay from a linked worktree."""
    root = _git_repo(tmp_path / "project.git")
    (root / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    _write_local(root, [MAIN_ONLY])
    _git_commit(root)
    wt = _add_worktree(root, tmp_path / "wt")
    assert local_dict_path(wt / "doc.qmd") == \
        root / ".claude" / "scientific-writing" / "dictionary.json"


def test_worktree_lint_sees_main_checkout_overlay(tmp_path, capsys):
    root = _git_repo(tmp_path / "main")
    (root / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    _write_local(root, [MAIN_ONLY])
    _git_commit(root)
    wt = _add_worktree(root, tmp_path / "wt")
    q = _qmd(wt, "упомянута мейнметка в тексте\n")
    main([str(q), "--json"])
    assert "local-main-only" in capsys.readouterr().out


def test_worktree_prefers_own_tracked_overlay(tmp_path, capsys):
    root = _git_repo(tmp_path / "main")
    _write_local(root, [WT_OWN])
    _git_commit(root)  # tracked overlay -> checked out into the linked worktree
    wt = _add_worktree(root, tmp_path / "wt")
    _write_local(root, [MAIN_ONLY])  # main's copy diverges; the worktree keeps its own
    q = _qmd(wt, "веткаметка и мейнметка в одном тексте\n")
    main([str(q), "--json"])
    ids = {f["id"] for f in json.loads(capsys.readouterr().out)}
    assert "local-wt" in ids and "local-main-only" not in ids


def test_effective_entries_returns_cached_object_on_repeat(tmp_path):
    root = _git_repo(tmp_path)
    _write_local(root, [MASTER])
    q = _qmd(root, "текст\n")
    first = lint_prose.effective_entries(q)
    second = lint_prose.effective_entries(q)
    assert first is second


def test_effective_entries_shared_within_repo_distinct_across_repos(tmp_path):
    # Identical overlay content on purpose: only the path in the cache key keeps the two
    # repos from colliding.
    root_a = _git_repo(tmp_path / "a")
    root_b = _git_repo(tmp_path / "b")
    _write_local(root_a, [MASTER])
    _write_local(root_b, [MASTER])
    qa1 = _qmd(root_a, "текст\n")
    qa2 = root_a / "other.qmd"
    qa2.write_text("текст\n", encoding="utf-8")
    qb = _qmd(root_b, "текст\n")
    same = lint_prose.effective_entries(qa1)
    assert lint_prose.effective_entries(qa2) is same
    assert lint_prose.effective_entries(qb) is not same


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


def test_malformed_local_returns_3_and_message(tmp_path, capsys):
    root = _git_repo(tmp_path)
    d = root / ".claude" / "scientific-writing"
    d.mkdir(parents=True)
    (d / "dictionary.json").write_text("{broken", encoding="utf-8")
    q = _qmd(root, "любой текст\n")
    rc = main([str(q)])
    assert rc == 3
    assert "ошибка локального словаря" in capsys.readouterr().err


def test_forced_missing_local_dictionary_errors(tmp_path, capsys):
    q = tmp_path / "doc.qmd"
    q.write_text("текст\n", encoding="utf-8")
    rc = main([str(q), "--local-dictionary", str(tmp_path / "nope.json")])
    assert rc == 3
    assert "ошибка локального словаря" in capsys.readouterr().err


def test_config_error_exit_3_distinct_from_argparse_exit_2(tmp_path):
    """A CLI usage mistake (argparse exits 2) must stay distinguishable from a broken
    local dictionary (exit 3): the hook maps only the latter to its dictionary message."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--bogus", "doc.qmd"])
    assert excinfo.value.code == 2
    root = _git_repo(tmp_path)
    d = root / ".claude" / "scientific-writing"
    d.mkdir(parents=True)
    (d / "dictionary.json").write_text("{broken", encoding="utf-8")
    q = _qmd(root, "любой текст\n")
    assert main([str(q)]) == 3


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
    p = _write(tmp_path, [{"id": "x", "layer": "doc", "pattern": "a", "severity": "Error",
                           "message": "m"}])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_non_string_except(tmp_path):
    p = _write(tmp_path, [{"id": "x", "layer": "doc", "pattern": "a", "severity": "warn",
                           "message": "m", "except": ["b", "c"]}])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_string_except_ok(tmp_path):
    p = _write(tmp_path, [{"id": "x", "layer": "doc", "pattern": "a", "severity": "warn",
                           "message": "m", "except": "b"}])
    assert load_raw(p)[0]["except"] == "b"


def test_load_raw_unhashable_severity(tmp_path):
    p = _write(tmp_path, [{"id": "x", "layer": "doc", "pattern": "a", "severity": ["error"],
                           "message": "m"}])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_non_string_message(tmp_path):
    p = _write(tmp_path, [{"id": "x", "layer": "doc", "pattern": "a", "severity": "warn",
                           "message": ["m"]}])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_non_bool_disabled(tmp_path):
    p = _write(tmp_path, [{"id": "x", "disabled": "false"}])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_disabled_false_still_validated(tmp_path):
    p = _write(tmp_path, [{"id": "x", "layer": "doc", "pattern": "a", "severity": "warn",
                           "message": "m", "disabled": False}])
    assert load_raw(p)[0]["_rx"].search("a")


def test_load_raw_bad_layer(tmp_path):
    p = _write(tmp_path, [{"id": "x", "layer": "wrong", "pattern": "a", "severity": "warn",
                           "message": "m"}])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_new_entry_requires_layer(tmp_path):
    p = _write(tmp_path, [{"id": "x", "pattern": "a", "severity": "warn", "message": "m"}])
    with pytest.raises(ConfigError):
        load_raw(p)


def test_load_raw_override_inherits_layer(tmp_path):
    """An override-by-id keeps the base entry's layer — no need to restate it."""
    p = _write(tmp_path, [{"id": "jargon-kogorta", "severity": "error"}])
    assert "layer" not in load_raw(p, frozenset({"jargon-kogorta"}))[0]


def test_merged_override_inherits_base_layer():
    """Same inheritance after `merge_entries`, not only in the raw overlay dict."""
    base = [{"id": "jargon-kogorta", "pattern": "когорт", "severity": "warn",
             "message": "m", "layer": "universal"}]
    merged = merge_entries(base, [{"id": "jargon-kogorta", "severity": "error"}])
    assert [e for e in merged if e["id"] == "jargon-kogorta"][0]["layer"] == "universal"


def test_load_raw_layer_universal_is_legal(tmp_path):
    """The enum allows every value in an overlay; `doc` is not the only legal one."""
    p = _write(tmp_path, [{"id": "x", "layer": "universal", "pattern": "a", "severity": "warn",
                           "message": "m"}])
    assert load_raw(p)[0]["layer"] == "universal"
