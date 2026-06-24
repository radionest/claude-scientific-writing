import json, os, subprocess, textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "text-lint.sh"


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


def test_passes_when_only_warn(tmp_path):
    repo = _repo(tmp_path)
    (repo / "r.qmd").write_text("чистая проза\nпациенты когорты\n", encoding="utf-8")
    _git(repo, "add", "r.qmd")
    r = _run_hook(repo, "git commit -m x")
    assert r.returncode == 0


def test_ignores_non_git_commands(tmp_path):
    repo = _repo(tmp_path)
    r = _run_hook(repo, "ls -la")
    assert r.returncode == 0


def test_skips_tests_fixtures(tmp_path):
    # test fixtures intentionally contain calques (the plugin's own oracle) -> must NOT block
    repo = _repo(tmp_path)
    (repo / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)
    (repo / "tests" / "fixtures" / "calques.qmd").write_text("референсный стандарт\n", encoding="utf-8")
    _git(repo, "add", "tests/fixtures/calques.qmd")
    r = _run_hook(repo, "git commit -m x")
    assert r.returncode == 0
