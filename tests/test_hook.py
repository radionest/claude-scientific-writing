import json, os, subprocess, textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "text-lint.sh"


def test_plugin_manifest_omits_hooks_field():
    # "hooks" must stay absent: it duplicates the auto-read hooks/hooks.json and errors
    # the plugin in /plugin. "version" is kept and bumped manually per release.
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert "hooks" not in manifest
    assert manifest.get("version")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _run_hook(cwd, command):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(["bash", str(HOOK)], cwd=cwd, input=payload,
                          text=True, capture_output=True)


def _repo(tmp_path):
    _git(tmp_path, "init"); _git(tmp_path, "add", "-A")
    (tmp_path / "r.qmd").write_text("чистая проза\n", encoding="utf-8")
    _git(tmp_path, "add", "r.qmd"); _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init")
    return tmp_path


def test_blocks_on_new_error_calque(tmp_path):
    repo = _repo(tmp_path)
    (repo / "r.qmd").write_text("чистая проза\nреференсный стандарт\n", encoding="utf-8")
    _git(repo, "add", "r.qmd")
    r = _run_hook(repo, "git commit -m x")
    assert r.returncode == 2
    assert "referens" in (r.stdout + r.stderr)


def _overlay(repo, entries):
    d = repo / ".claude" / "scientific-writing"
    d.mkdir(parents=True)
    (d / "dictionary.json").write_text(json.dumps({"entries": entries}, ensure_ascii=False),
                                       encoding="utf-8")


def test_passes_when_only_warn(tmp_path):
    # The warn must come from a synthetic overlay rule, not from live canon (#48):
    # retuning any canon entry (e.g. jargon-kogorta) must not flip this test.
    repo = _repo(tmp_path)
    _overlay(repo, [{
        "id": "e2e-warn-only", "layer": "doc", "pattern": "\\bзондажн\\w*",
        "severity": "warn", "message": "синтетическое warn-правило e2e-теста хука",
    }])
    (repo / "r.qmd").write_text("чистая проза\nзондажная оценка\n", encoding="utf-8")
    _git(repo, "add", ".claude/scientific-writing/dictionary.json", "r.qmd")
    r = _run_hook(repo, "git commit -m x")
    # exit 0 still rests on the fixtures' baseline: live canon has no error hit on this text.
    assert r.returncode == 0
    assert "[warn] e2e-warn-only" in (r.stdout + r.stderr)  # the warn path was exercised


def test_ignores_non_git_commands(tmp_path):
    repo = _repo(tmp_path)
    r = _run_hook(repo, "ls -la")
    assert r.returncode == 0


def test_lints_user_tests_fixtures_path(tmp_path):
    # issue #102: the fixtures exemption is path identity, not a suffix — a user
    # file under tests/fixtures/ is not the plugin's oracle and must be linted
    repo = _repo(tmp_path)
    d = repo / "tests" / "fixtures"
    d.mkdir(parents=True)
    (d / "calques.qmd").write_text("референсный стандарт\n", encoding="utf-8")
    _git(repo, "add", "tests/fixtures/calques.qmd")
    r = _run_hook(repo, "git commit -m x")
    assert r.returncode == 2


def test_skips_plugin_repo_own_fixtures(tmp_path):
    # issue #102, the other side: in a plugin-shaped repo (dev checkout) the own
    # fixtures are the oracle — identity with the repo's tests/fixtures keeps them exempt
    repo = _repo(tmp_path)
    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin" / "plugin.json").write_text('{"version": "1.0.0"}',
                                                         encoding="utf-8")
    d = repo / "tests" / "fixtures"
    d.mkdir(parents=True)
    (d / "calques.qmd").write_text("референсный стандарт\n", encoding="utf-8")
    _git(repo, "add", "tests/fixtures/calques.qmd")
    r = _run_hook(repo, "git commit -m x")
    assert r.returncode == 0


def test_lints_user_eval_corpus_path(tmp_path):
    # issue #89: the eval-corpus exemption is path identity, not a suffix — a user
    # file at tests/eval/lint-bad.qmd is not the plugin's corpus and must be linted
    repo = _repo(tmp_path)
    d = repo / "tests" / "eval"
    d.mkdir(parents=True)
    (d / "lint-bad.qmd").write_text("референсный стандарт\n", encoding="utf-8")
    _git(repo, "add", "tests/eval/lint-bad.qmd")
    r = _run_hook(repo, "git commit -m x")
    assert r.returncode == 2


def test_skips_plugin_repo_own_eval_corpus(tmp_path):
    # issue #89, the other side: in a plugin-shaped repo (dev checkout) the own
    # corpus is the oracle — identity with the repo's lint-bad.qmd keeps it exempt
    repo = _repo(tmp_path)
    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin" / "plugin.json").write_text('{"version": "1.0.0"}',
                                                         encoding="utf-8")
    d = repo / "tests" / "eval"
    d.mkdir(parents=True)
    (d / "lint-bad.qmd").write_text("референсный стандарт\n", encoding="utf-8")
    _git(repo, "add", "tests/eval/lint-bad.qmd")
    r = _run_hook(repo, "git commit -m x")
    assert r.returncode == 0


def test_blocks_with_dict_message_on_malformed_local_dict(tmp_path):
    repo = _repo(tmp_path)
    d = repo / ".claude" / "scientific-writing"
    d.mkdir(parents=True)
    (d / "dictionary.json").write_text("{broken", encoding="utf-8")
    (repo / "r.qmd").write_text("чистая проза\nещё чистая проза\n", encoding="utf-8")
    _git(repo, "add", "r.qmd")
    r = _run_hook(repo, "git commit -m x")
    out = r.stdout + r.stderr
    assert r.returncode == 2          # still blocks
    assert "словаря" in out           # names the local dictionary
    assert "кальки" not in out        # NOT the calque message — the file has none
