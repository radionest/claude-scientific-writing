"""Review plan: `canon/review-dimensions.json` is the single source of the
prose-reviewer dispatch — registry ids match the agent contract, the scenario
documents match the pre-plan hand dispatch, and the CLI contract (JSON shape,
exit codes) holds."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from lib import review_plan
from lib.lint_prose import ConfigError
from lib.review_plan import load_registry, main, plan

ROOT = Path(__file__).resolve().parents[1]

ALWAYS = {"calques", "repeats", "structure", "terminology", "render"}
FULL_ORDER = [
    "calques", "repeats", "structure", "terminology", "render",
    "genre", "discussion", "argument", "fidelity", "evidence",
]

REPORT = """# Отчёт

## Реферат
Медиана выживаемости составила 92 % (n = 40).

## Введение
Изучена связь курения с риском рецидива у пациентов после резекции.

## Материалы и методы
Дизайн — ретроспективная когорта, сорок пациентов.

## Результаты
Рецидив отмечен у двенадцати пациентов [@ivanov2020].

## Обсуждение
Главный результат — снижение частоты рецидива на 3 % в год.

## Заключение
Курение ассоциировано с риском рецидива.
"""

REPORT_NO_DISCUSSION = REPORT.replace(
    """## Обсуждение
Главный результат — снижение частоты рецидива на 3 % в год.

""", "")

CLAIMS = json.dumps({"claim_id": "c1", "section": "Результаты",
                     "claim_kind": "headline", "evidence": "tbl:recurrence",
                     "citation_keys": ["ivanov2020"], "support_status": "supported"},
                    ensure_ascii=False) + "\n"

INTRO_LINE = "Изучена связь курения с риском рецидива у пациентов после резекции."

NESTED = """# Отчёт

## Методы
Проза методов.

### Материалы и методы сбора
Проза сбора.

### Критерии включения
Проза критериев.
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base: str,
           edited: str) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "doc.qmd").write_text(base, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "doc.qmd"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-q", "--no-verify", "-m", "base"],
                   check=True)
    (tmp_path / "doc.qmd").write_text(edited, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "doc.qmd"], check=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path / "doc.qmd"


def ids(result) -> set[str]:
    return {d.id for d in result.dimensions}


def test_registry_ids_match_prose_reviewer():
    reg_ids = [e["id"] for e in load_registry()]
    assert len(reg_ids) == len(set(reg_ids)), "duplicate registry ids"
    agent = (ROOT / "agents" / "prose-reviewer.md").read_text(encoding="utf-8")
    assert sorted(re.findall(r"\*\*([a-z-]+)\*\*", agent)) == sorted(reg_ids)


def test_registry_contract_fields():
    for e in load_registry():
        assert set(e) == {"id", "tier", "when", "skills", "source"}
        assert e["tier"] in {"fast", "strong"}
        agent_file = e["source"].rsplit("#", 1)[0]
        assert e["source"] == f"{agent_file}#{e['id']}"
        agent = (ROOT / agent_file).read_text(encoding="utf-8")
        for s in e["skills"]:
            assert s in agent, f"{e['id']}: skill «{s}» не назван у {agent_file}"


def test_registry_carries_tier():
    tiers = {e["id"]: e["tier"] for e in load_registry()}
    assert tiers == {
        "calques": "strong", "repeats": "fast", "structure": "fast", "terminology": "fast",
        "render": "fast", "genre": "fast", "discussion": "strong", "argument": "strong",
        "fidelity": "strong", "evidence": "strong",
    }


def test_plan_entry_carries_tier(tmp_path):
    doc = write(tmp_path, "article.qmd", REPORT)
    write(tmp_path, "article.claims.jsonl", CLAIMS)
    result = plan(doc, mode="full", before=doc)
    tiers = {d.id: d.tier for d in result.dimensions}
    assert tiers["calques"] == "strong" and tiers["evidence"] == "strong"
    assert tiers["repeats"] == "fast" and tiers["structure"] == "fast"


def test_house_lanes_override_tier(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    d = tmp_path / ".claude" / "scientific-writing"
    d.mkdir(parents=True)
    (d / "house.json").write_text(
        json.dumps({"lanes": {"calques": "fast", "repeats": "strong"}}, ensure_ascii=False),
        encoding="utf-8")
    doc = write(tmp_path, "report.qmd", REPORT)
    result = plan(doc, mode="light")
    tiers = {x.id: x.tier for x in result.dimensions}
    assert tiers["calques"] == "fast" and tiers["repeats"] == "strong"


def test_full_article_scenario(tmp_path):
    doc = write(tmp_path, "article.qmd", REPORT)
    write(tmp_path, "article.claims.jsonl", CLAIMS)
    result = plan(doc, mode="full", before=doc)
    assert [d.id for d in result.dimensions] == FULL_ORDER


def test_report_without_discussion_light(tmp_path):
    doc = write(tmp_path, "report.qmd", REPORT_NO_DISCUSSION)
    assert ids(plan(doc, mode="light")) == ALWAYS


def test_one_phrase_diff_edit_with_before(tmp_path, monkeypatch):
    doc = staged(tmp_path, monkeypatch, REPORT_NO_DISCUSSION,
                 REPORT_NO_DISCUSSION.replace(INTRO_LINE,
                                              "Изучена связь курения с риском рецидива."))
    assert ids(plan(doc, mode="diff", before=doc)) == ALWAYS | {"fidelity"}


def test_diff_two_substantive_lines_include_argument(tmp_path, monkeypatch):
    edited = REPORT_NO_DISCUSSION.replace(
        INTRO_LINE, "Изучена связь курения с риском рецидива у пациентов.").replace(
        "Дизайн — ретроспективная когорта, сорок пациентов.",
        "Дизайн — проспективная когорта, сорок пациентов.")
    doc = staged(tmp_path, monkeypatch, REPORT_NO_DISCUSSION, edited)
    result = plan(doc, mode="diff")
    entry = next(d for d in result.dimensions if d.id == "argument")
    assert entry.reason.startswith("в diff изменены строки содержательного раздела")


def test_diff_non_substantive_lines_do_not_count(tmp_path, monkeypatch):
    edited = REPORT.replace("Медиана выживаемости составила 92 % (n = 40).",
                            "Медиана выживаемости составила 93 % (n = 40).").replace(
        "Главный результат — снижение частоты рецидива на 3 % в год.",
        "Главный результат — снижение частоты рецидива на 4 % в год.")
    doc = staged(tmp_path, monkeypatch, REPORT, edited)
    assert "argument" not in ids(plan(doc, mode="diff"))


def test_nested_substantive_headings_do_not_truncate(tmp_path, monkeypatch):
    edited = NESTED.replace("Проза методов.", "Проза методов уточнена.").replace(
        "Проза критериев.", "Проза критериев уточнена.")
    doc = staged(tmp_path, monkeypatch, NESTED, edited)
    assert "argument" in ids(plan(doc, mode="diff"))


def test_plan_rejects_unknown_mode(tmp_path):
    doc = write(tmp_path, "report.qmd", REPORT)
    with pytest.raises(ValueError, match="mode"):
        plan(doc, mode="bogus")


def test_no_discussion_no_genre_discussion(tmp_path):
    doc = write(tmp_path, "report.qmd", REPORT_NO_DISCUSSION)
    assert {"genre", "discussion"} - ids(plan(doc, mode="full")) == {"genre", "discussion"}
    doc.write_text(REPORT, encoding="utf-8")
    assert {"genre", "discussion"} <= ids(plan(doc, mode="full"))


def test_before_adds_fidelity(tmp_path):
    doc = write(tmp_path, "report.qmd", REPORT)
    assert "fidelity" not in ids(plan(doc, mode="full"))
    assert "fidelity" in ids(plan(doc, mode="full", before=doc))


def test_invalid_claims_registry_excludes_evidence(tmp_path):
    doc = write(tmp_path, "article.qmd", REPORT)
    claims = write(tmp_path, "article.claims.jsonl",
                   json.dumps({"claim_id": "c1", "claim_kind": "wow",
                               "support_status": "fine"}, ensure_ascii=False) + "\n")
    assert "evidence" not in ids(plan(doc, mode="full"))
    claims.write_text(CLAIMS.replace('"citation_keys": ["ivanov2020"]',
                                     '"citation_keys": ["netu2021"]'), encoding="utf-8")
    assert "evidence" in ids(plan(doc, mode="full"))


def test_light_excludes_argument(tmp_path):
    doc = write(tmp_path, "article.qmd", REPORT)
    write(tmp_path, "article.claims.jsonl", CLAIMS)
    result = ids(plan(doc, mode="light"))
    assert "argument" not in result
    assert ALWAYS <= result


def test_cli_json_shape_and_exit_codes(tmp_path, capsys):
    doc = write(tmp_path, "report.qmd", REPORT)
    assert main([str(doc), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["mode"] == "diff"
    assert {d["id"] for d in data["dimensions"]} == ALWAYS | {"genre", "discussion"}
    assert all(set(d) == {"id", "tier", "when", "reason", "covered_by_lint"} and d["reason"]
               for d in data["dimensions"])
    assert main([str(tmp_path / "nope.qmd"), "--json"]) == 2
    with pytest.raises(SystemExit) as exc:
        main([str(doc), "--mode", "bogus"])
    assert exc.value.code == 2


def test_cli_before_path(tmp_path, capsys):
    doc = write(tmp_path, "report.qmd", REPORT)
    assert main([str(doc), "--mode", "full", "--before", str(doc), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {d["id"] for d in data["dimensions"]} >= ALWAYS | {"fidelity"}
    assert main([str(doc), "--before", str(tmp_path / "nope.qmd"), "--json"]) == 2


def test_broken_registry_configerror(tmp_path):
    bad = write(tmp_path, "bad.json", '{"entries": [{"id": "calques"}]}')
    with pytest.raises(ConfigError):
        load_registry(bad)


def test_cli_broken_registry_exits_3(tmp_path, monkeypatch):
    bad = write(tmp_path, "bad.json", "{not json")
    doc = write(tmp_path, "report.qmd", REPORT)
    monkeypatch.setattr(review_plan, "_REGISTRY", bad)
    assert main([str(doc), "--json"]) == 3
