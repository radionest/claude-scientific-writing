"""Model lanes: `tier_of` follows the registry and the pack's `lanes`, configuration
errors are loud (`ConfigError`/`ValueError`, never a silent `fast`), and the boundary
holds — the lib/canon core knows no harness names and no tracked file names a model,
except the sanctioned workflow. Harness-side behavior is pinned by the adapter tests
below (`build_tasks`/`audit_results`, the read-only check scripts)."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from lib import lanes as lanes_mod
from lib.lane_measure import GoldItem, load_gold, main as lane_measure_main, measure, score_run
from lib.lanes import load_lanes, tier_of
from lib.lint_prose import ConfigError
from lib.review_plan import PlanEntry, ReviewPlan
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


# --- harness adapters ---

sys.path.insert(0, str(ROOT / "hermes"))
import sw_bridge  # noqa: E402

CHECK_SCRIPTS = [ROOT / "hermes" / "lanes_check.py",
                 ROOT / ".zcode" / "scripts" / "lanes_check.py"]


def _snapshot(home: Path) -> dict[str, bytes]:
    return {str(p.relative_to(home)): p.read_bytes()
            for p in sorted(home.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("script", CHECK_SCRIPTS, ids=lambda p: p.parent.name)
def test_check_scripts_write_nothing(tmp_path, script):
    before = _snapshot(tmp_path)
    env = {**os.environ, "HOME": str(tmp_path), "PYTHONPATH": str(ROOT),
           "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, str(script)], env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "writer" in r.stdout  # the «роль — полоса — модель» table
    assert _snapshot(tmp_path) == before


def test_build_tasks_batch_by_lane():
    plan = ReviewPlan(mode="full", dimensions=(
        PlanEntry(id="calques", tier="strong", when="always", reason=""),
        PlanEntry(id="repeats", tier="fast", when="always", reason=""),
        PlanEntry(id="terminology", tier="fast", when="always", reason="",
                  covered_by_lint=True)))
    tasks = sw_bridge.build_tasks(plan)
    assert len(tasks) == 2
    assert {t["group"] for t in tasks} == {"sw-review"}  # one batch, one common group
    assert [t["model"] for t in tasks] == ["sw-strong", "sw-fast"]
    assert "terminology" not in {t["id"] for t in tasks}
    for t in tasks:
        assert set(t) == {"id", "group", "goal", "model", "output_schema"}
        assert t["goal"].startswith(f"- **{t['id']}** — ")
        assert t["output_schema"]["items"]["required"] == \
            ["file", "line", "dimension", "severity", "problem", "fix"]


def test_audit_results_flags_schema_and_route():
    tasks = sw_bridge.build_tasks(ReviewPlan(mode="full", dimensions=(
        PlanEntry(id="calques", tier="strong", when="always", reason=""),
        PlanEntry(id="repeats", tier="fast", when="always", reason=""))))
    ok = sw_bridge.audit_results(tasks, [
        {"id": "calques", "schema_valid": True, "route": "sw-strong"},
        {"id": "repeats", "schema_valid": True, "route": "sw-fast"}])
    assert ok["ok"] == ["calques", "repeats"] and ok["all_ok"] is True

    bad_schema = sw_bridge.audit_results(tasks, [
        {"id": "calques", "schema_valid": False, "route": "sw-strong"},
        {"id": "repeats", "schema_valid": True, "route": "sw-fast"}])
    assert bad_schema["schema_invalid"] == ["calques"] and not bad_schema["all_ok"]

    bad_route = sw_bridge.audit_results(tasks, [
        {"id": "calques", "schema_valid": True, "route": "sw-strong"},
        {"id": "repeats", "schema_valid": True, "route": "sw-strong"}])
    assert bad_route["route_mismatch"] == ["repeats"] and not bad_route["all_ok"]

    missing = sw_bridge.audit_results(tasks, [{"id": "calques", "schema_valid": True,
                                               "route": "sw-strong"}])
    assert missing["missing"] == ["repeats"] and not missing["all_ok"]

    unexpected = sw_bridge.audit_results(tasks, [
        {"id": "calques", "schema_valid": True, "route": "sw-strong"},
        {"id": "repeats", "schema_valid": True, "route": "sw-fast"},
        {"id": "ghost", "schema_valid": True, "route": "sw-fast"}])
    assert unexpected["unexpected"] == ["ghost"] and not unexpected["all_ok"]


# --- lane measurement ---

def test_score_run_hits_only_in_anchor_ranges():
    gold = [GoldItem("calques", 10, 12), GoldItem("calques", 30, 30),
            GoldItem("repeats", 40, 45)]
    findings = [
        {"file": "d.qmd", "line": 11, "dimension": "calques"},  # inside the range
        {"file": "d.qmd", "line": 30, "dimension": "calques"},  # single-line anchor
        {"file": "d.qmd", "line": 13, "dimension": "calques"},  # outside → extra
        {"file": "d.qmd", "line": 11, "dimension": "repeats"},  # wrong dimension: extra in its own bucket
        {"file": "d.qmd", "line": 41, "dimension": "repeats"},  # hit
    ]
    score = score_run(gold, findings)
    assert score["calques"]["hits"] == 2 and score["calques"]["extra"] == 1
    assert score["repeats"]["hits"] == 1 and score["repeats"]["extra"] == 1
    assert score["calques"]["covered"] == {0, 1}


def test_measure_verdicts_and_any_reviewer(tmp_path):
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({"items": [
        {"file": "d.qmd", "dimension": "calques", "line_start": 10, "line_end": 12},
        {"file": "d.qmd", "dimension": "calques", "line_start": 30, "line_end": 30},
        {"file": "d.qmd", "dimension": "calques", "line_start": 50, "line_end": 52},
        {"file": "d.qmd", "dimension": "repeats", "line_start": 40, "line_end": 45},
        {"file": "d.qmd", "dimension": "fidelity", "line_start": 60, "line_end": 60},
    ]}), encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "fast.json").write_text(json.dumps({"runs": [
        {"dimension": "calques", "tier": "fast",
         "findings": [{"file": "d.qmd", "line": 10, "dimension": "calques"}]}]}),
        encoding="utf-8")
    (runs / "strong.json").write_text(json.dumps({"runs": [
        {"dimension": "calques", "tier": "strong",
         "findings": [{"file": "d.qmd", "line": 50, "dimension": "calques"}]},
        {"dimension": "repeats", "tier": "strong",
         "findings": [{"file": "d.qmd", "line": 42, "dimension": "repeats"}]}]}),
        encoding="utf-8")
    report = measure(gold, runs)
    calques = report["dimensions"]["calques"]
    assert calques["verdict"] == "ok" and calques["gold"] == 3
    assert calques["runs"]["fast"]["hits"] == 1 and calques["runs"]["strong"]["hits"] == 1
    assert calques["any_reviewer"]["found"] == 2
    assert calques["any_reviewer"]["recall"] == 0.667
    assert report["dimensions"]["repeats"]["verdict"] == "no_verdict"  # 1 gold finding < 3
    assert report["dimensions"]["fidelity"]["verdict"] == "excluded"  # not measured


def test_lane_measure_malformed_gold(tmp_path):
    bad = tmp_path / "gold.json"
    bad.write_text('{"items": [{"dimension": "calques"}]}', encoding="utf-8")
    with pytest.raises(ConfigError, match="line_start"):
        load_gold(bad)
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_gold(bad)


def test_lane_measure_cli_gold_required_and_report(tmp_path):
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({"items": [
        {"file": "d.qmd", "dimension": "calques", "line_start": 1, "line_end": 2},
        {"file": "d.qmd", "dimension": "calques", "line_start": 5, "line_end": 6},
        {"file": "d.qmd", "dimension": "calques", "line_start": 9, "line_end": 9},
    ]}), encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "only.json").write_text(json.dumps({"runs": [
        {"dimension": "calques", "tier": "strong",
         "findings": [{"file": "d.qmd", "line": 1, "dimension": "calques"}]}]}),
        encoding="utf-8")
    out = tmp_path / "report.json"
    assert lane_measure_main(["--gold", str(gold), "--runs", str(runs), "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["dimensions"]["calques"]["any_reviewer"]["recall"] == 0.333
    assert lane_measure_main(["--gold", str(gold), "--runs", str(runs)]) == 0
    with pytest.raises(SystemExit) as exc:
        lane_measure_main(["--runs", str(runs)])
    assert exc.value.code == 2
