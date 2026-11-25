"""Model lanes: `tier_of` follows the registry and the pack's `lanes`, configuration
errors are loud (`ConfigError`/`ValueError`, never a silent `fast`), and the boundary
holds — the lib/canon core knows no harness names and no tracked file names a model,
except the sanctioned workflow. Harness-side behavior is pinned by the adapter tests
below (`build_tasks`/`audit_results`, the read-only check scripts)."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from lib import lanes as lanes_mod
from lib.lanes import load_lanes, tier_of
from lib.lint_prose import ConfigError
from lib.review_plan import load_registry

ROOT = Path(__file__).resolve().parents[1]

# lib/canon must not know the harnesses (the two sanctioned lines are a path mention in
# a provenance note and the linter's overlay convention — not harness coupling). The
# model-id tokens are assembled from fragments so this scan does not match itself.
_MODEL_TOKENS = ("anth" + "ropic", "open" + "ai", "ki" + "mi", "accou" + "nt:",
                 "glm-\\d", "z" + "ai-")
BANNED = re.compile(r"zcode|claude code|claude-code|hermes|claude_plugin_root|delegate_task"
                    + "|" + "|".join(_MODEL_TOKENS), re.IGNORECASE)
ALLOWED_LINES = {
    ROOT / "lib" / "docx_review.py": "~/.zcode/scripts/docx_review.py",
    ROOT / "lib" / "lint_prose.py": ".claude/scientific-writing/",
}
# Model identifiers stay out of the public repo: the harness assigns models to lanes.
MODEL_ID = re.compile("|".join(_MODEL_TOKENS), re.IGNORECASE)
MODEL_ID_EXCEPT = ".zcode/workflows/roadmap-write-review-fix.dwf.ts"


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def _write_house(root: Path, data) -> Path:
    d = root / ".claude" / "scientific-writing"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "house.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _doc(root: Path) -> Path:
    p = root / "doc.qmd"
    p.write_text("Проза.\n", encoding="utf-8")
    return p


# --- tier_of ---

def test_tier_of_follows_registry():
    assert tier_of("calques") == "strong"
    assert tier_of("evidence") == "strong"
    assert tier_of("repeats") == "fast"
    assert tier_of("render") == "fast"


def test_roles_carry_declared_lanes():
    lanes = load_lanes()
    assert (lanes.writer, lanes.judge) == ("fast", "typesafe/jev-1.14")
    assert tier_of("writer") == "fast"
    assert tier_of("judge") == "typesafe/jev-1.14"


def test_tier_of_follows_house_json(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, {"lanes": {"calques": "fast", "repeats": "strong"}})
    doc = _doc(root)
    assert tier_of("calques", doc) == "fast"
    assert tier_of("repeats", doc) == "strong"
    assert tier_of("argument", doc) == "strong"  # an unoverridden dimension stays


def test_tier_of_unknown_name_is_value_error():
    with pytest.raises(ValueError, match="неизвестное имя"):
        tier_of("nope")
    with pytest.raises(ValueError):
        load_lanes().tier_of("terminology2")


# --- configuration errors ---

def test_broken_lanes_json(tmp_path, monkeypatch):
    bad = tmp_path / "lanes.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(lanes_mod, "_LANES_PATH", bad)
    with pytest.raises(ConfigError):
        load_lanes()
    bad.write_text('{"writer": "fast"}', encoding="utf-8")
    with pytest.raises(ConfigError, match="writer, judge"):
        load_lanes()


def test_house_lanes_outside_registry(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, {"lanes": {"genre2": "fast"}})
    with pytest.raises(ConfigError, match="вне реестра"):
        tier_of("calques", _doc(root))


def test_house_lanes_wrong_tier(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, {"lanes": {"calques": "bogus"}})
    with pytest.raises(ConfigError, match="недопустимая полоса"):
        tier_of("calques", _doc(root))


# --- the boundary: core knows no harness, repo knows no model id ---

def test_core_free_of_harness_names():
    offenders = []
    for p in sorted(ROOT.glob("lib/**/*.py")) + sorted(ROOT.glob("canon/**/*")):
        if not p.is_file():
            continue
        allow = ALLOWED_LINES.get(p)
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if allow and allow in line:
                continue
            m = BANNED.search(line)
            if m:
                offenders.append(f"{p.relative_to(ROOT)}:{i}: {m.group(0)}")
    assert not offenders, "harness names leaked into the core:\n" + "\n".join(offenders)


def test_no_model_ids_outside_roadmap_workflow():
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], check=True,
                             capture_output=True, text=True).stdout.splitlines()
    offenders = []
    for rel in tracked:
        if rel == MODEL_ID_EXCEPT:
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            m = MODEL_ID.search(line)
            if m:
                offenders.append(f"{rel}:{i}: {m.group(0)}")
    assert not offenders, "model ids leaked into the repo:\n" + "\n".join(offenders)


# --- the agent split ---

def _bold_ids(path: Path) -> list[str]:
    return re.findall(r"\*\*([a-z-]+)\*\*", path.read_text(encoding="utf-8"))


def test_registry_ids_split_across_agents_by_tier():
    registry = load_registry()
    fast = _bold_ids(ROOT / "agents" / "prose-reviewer.md")
    strong = _bold_ids(ROOT / "agents" / "prose-reviewer-strong.md")
    ids = [e["id"] for e in registry]
    assert sorted(fast + strong) == sorted(ids), "registry ids != the two agents' bold ids"
    assert sorted(set(fast) & set(strong)) == [], "a dimension is bold in both agents"
    for e in registry:
        home = fast if e["tier"] == "fast" else strong
        assert e["id"] in home, f"{e['id']} ({e['tier']}) is not bold in its lane's agent"


# --- harness adapters (bridges, snapshots) land with their commits ---
