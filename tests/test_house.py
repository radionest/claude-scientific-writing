"""Project pack (`<git-root>/.claude/scientific-writing/house.json`): discovery and
validation (`ConfigError` → exit 3), the wiring into the linter (the `doc-term-*` rule
records, the `doc-abbrev-*` allow lists) and the review plan's `covered_by_lint`."""
import json
import subprocess
from pathlib import Path

import pytest

from lib import lint_prose
from lib.house import house_path, load_house
from lib.lint_prose import ConfigError, effective_entries
from lib.lint_prose import main as lint_main
from lib.review_plan import plan
from lib.review_plan import main as plan_main

PACK = {
    "name": "rtk",
    "genre_default": "report",
    "terms": [{"canonical": "мастер-модель", "forbidden": ["прототип"],
               "caution": ["макет печени"], "note": "печатный макет печени"}],
    "abbreviations": [{"abbr": "ИОУЗИ",
                       "expansion": "интраоперационное ультразвуковое исследование"}],
    "passport": {"numbers": "точка", "list-markers": "дефис"},
    "norms": [{"id": "denominator-policy", "text": "Знаменатель n (%) явный.",
               "source": "протокол"}],
    "samples": ["Печень — орган-мишень."],
    "lanes": ["хирургия"],
}
FORBIDDEN_DOC = "Печать прототипа заняла два дня.\n"
CANON_DOC = "Печать мастер-модели заняла два дня.\n"


@pytest.fixture(autouse=True)
def _clear_caches():
    # house_path/effective_entries cache per git root and rule-set key; the tmp repos
    # below must not leak into each other.
    lint_prose._clear_caches()
    yield
    lint_prose._clear_caches()


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def _write_house(root: Path, data) -> Path:
    d = root / ".claude" / "scientific-writing"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "house.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _qmd(root: Path, text: str) -> Path:
    p = root / "doc.qmd"
    p.write_text(text, encoding="utf-8")
    return p


# --- discovery ---

def test_house_path_in_repo(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, PACK)
    assert house_path(root / "doc.qmd") == root / ".claude" / "scientific-writing" / "house.json"


def test_house_path_none_outside_repo(tmp_path):
    assert house_path(tmp_path / "doc.qmd") is None


def test_house_path_worktree_falls_back_to_main(tmp_path):
    """Same fallback contract as the overlay: with `.claude/` gitignored, a linked
    worktree reads the pack from the main checkout."""
    root = _git_repo(tmp_path / "main")
    (root / ".gitignore").write_text(".claude/\n", encoding="utf-8")
    _write_house(root, PACK)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c",
                    "user.email=t@example.com", "commit", "-q", "-m", "init"], check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(root), "worktree", "add", str(wt)], check=True)
    assert house_path(wt / "doc.qmd") == root / ".claude" / "scientific-writing" / "house.json"


# --- loading and validation ---

def test_load_house_parses_every_field(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, PACK)
    h = load_house(root / "doc.qmd")
    assert h.name == "rtk" and h.genre_default == "report"
    assert h.terms[0].canonical == "мастер-модель"
    assert h.terms[0].forbidden == ("прототип",)
    assert h.terms[0].caution == ("макет печени",)
    assert h.terms[0].note == "печатный макет печени"
    assert h.abbreviations[0].abbr == "ИОУЗИ"
    assert h.passport.numbers == "точка" and h.passport.list_markers == "дефис"
    assert h.norms[0].id == "denominator-policy"
    assert h.samples == ("Печень — орган-мишень.",)
    assert h.lanes == ("хирургия",)


def test_load_house_none_without_pack(tmp_path):
    root = _git_repo(tmp_path)
    assert load_house(root / "doc.qmd") is None


def test_empty_object_is_a_valid_pack(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, {})
    h = load_house(root / "doc.qmd")
    assert h.name == "" and h.terms == () and h.passport.numbers == ""


def test_broken_json_raises(tmp_path):
    root = _git_repo(tmp_path)
    p = root / ".claude" / "scientific-writing" / "house.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_house(root / "doc.qmd")


@pytest.mark.parametrize("bad,fragment", [
    ({"nane": "x"}, "неизвестные поля"),
    ({"terms": {"canonical": "x"}}, "списком объектов"),
    ({"terms": [{"canon": "x"}]}, "неизвестные поля записи"),
    ({"terms": [{"canonical": ""}]}, "строкового поля"),
    ({"terms": [{"canonical": "x", "forbidden": "y"}]}, "списком непустых строк"),
    ({"terms": [{"canonical": "x", "note": 5}]}, "строкой"),
    ({"abbreviations": [{"abbr": "ИОУЗИ"}]}, "строкового поля"),
    ({"passport": {"unknown": "x"}}, "неизвестные поля"),
    ({"passport": {"numbers": 5}}, "не строковые значения"),
    ({"norms": [{"id": "x"}]}, "строкового поля"),
    ({"samples": ["", "x"]}, "списком непустых строк"),
    ({"lanes": 5}, "списком непустых строк"),
])
def test_malformed_pack_raises_configerror(tmp_path, bad, fragment):
    root = _git_repo(tmp_path)
    _write_house(root, bad)
    with pytest.raises(ConfigError, match=fragment):
        load_house(root / "doc.qmd")


def test_duplicate_norm_ids_raise(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, {"norms": [{"id": "x", "text": "a"}, {"id": "x", "text": "b"}]})
    with pytest.raises(ConfigError, match="повтор id"):
        load_house(root / "doc.qmd")


# --- the linter: terms ride the rule records, abbreviations join the allow lists ---

def test_linter_names_the_synonym_and_the_canonical_term(tmp_path, capsys):
    root = _git_repo(tmp_path)
    _write_house(root, PACK)
    q = _qmd(root, FORBIDDEN_DOC)
    assert lint_main([str(q), "--json"]) == 0
    hits = [f for f in json.loads(capsys.readouterr().out) if f["id"] == "doc-term-canon"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "warn"
    assert hits[0]["matched"] == "прототипа"
    assert "мастер-модель" in hits[0]["message"]


def test_caution_yields_info_with_the_note(tmp_path, capsys):
    root = _git_repo(tmp_path)
    _write_house(root, PACK)
    q = _qmd(root, "Макет печени обсудили перед примеркой.\n")
    lint_main([str(q), "--json"])
    hits = [f for f in json.loads(capsys.readouterr().out) if f["id"] == "doc-term-caution"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "info"
    assert "печатный макет печени" in hits[0]["message"]


def test_without_pack_the_pack_rules_stay_silent(tmp_path, capsys):
    """«Без пакета молчат» holds for the effective set: the canon demo terms — which the
    bad/good oracle needs — never reach it."""
    root = _git_repo(tmp_path)
    q = _qmd(root, "Печать прототипа и макета печени заняла день.\n")
    assert lint_main([str(q), "--json"]) == 0
    ids = {f["id"] for f in json.loads(capsys.readouterr().out)}
    assert {"doc-term-canon", "doc-term-caution"} & ids == set()


def test_abbreviations_reach_the_allow_lists_without_duplicates(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, {**PACK, "abbreviations": [
        {"abbr": "ИОУЗИ", "expansion": "интраоперационное УЗИ"},
        {"abbr": "КТ-АГ", "expansion": "КТ-артериография"},
        {"abbr": "ИОУЗИ", "expansion": "интраоперационное УЗИ"}]})
    q = _qmd(root, "текст\n")
    _, checks = effective_entries(q)
    by_id = {e["id"]: e for e in checks}
    assert by_id["doc-abbrev-variants"]["allow"] == ["ИОУЗИ", "КТ-АГ"]
    assert by_id["doc-abbrev-first-use"]["allow"] == ["ИОУЗИ", "КТ-АГ"]


def test_pack_abbreviation_silences_the_variant_rule(tmp_path, capsys):
    root = _git_repo(tmp_path)
    _write_house(root, PACK)
    q = _qmd(root, "Контроль на ио-УЗИ, описание по протоколу ИОУЗИ.\n")
    lint_main([str(q), "--json"])
    assert "doc-abbrev-variants" not in capsys.readouterr().out


def test_no_local_ignores_the_pack(tmp_path, capsys):
    root = _git_repo(tmp_path)
    _write_house(root, PACK)
    q = _qmd(root, FORBIDDEN_DOC)
    assert lint_main([str(q), "--json", "--no-local"]) == 0
    assert "doc-term-canon" not in capsys.readouterr().out


def test_local_dictionary_does_not_disable_the_pack(tmp_path, capsys):
    """`--local-dictionary` forces the overlay file only: the pack keeps feeding the
    checks on top of it."""
    root = _git_repo(tmp_path)
    _write_house(root, PACK)
    q = _qmd(root, FORBIDDEN_DOC)
    overlay = tmp_path / "forced.json"
    overlay.write_text(json.dumps({"entries": []}, ensure_ascii=False), encoding="utf-8")
    assert lint_main([str(q), "--json", "--local-dictionary", str(overlay)]) == 0
    assert "doc-term-canon" in capsys.readouterr().out


def test_broken_pack_exits_3(tmp_path, capsys):
    root = _git_repo(tmp_path)
    p = root / ".claude" / "scientific-writing" / "house.json"
    p.parent.mkdir(parents=True)
    p.write_text("{broken", encoding="utf-8")
    q = _qmd(root, "текст\n")
    assert lint_main([str(q)]) == 3
    assert "house.json" in capsys.readouterr().err


# --- the review plan: terminology covered_by_lint ---

def test_plan_marks_terminology_covered(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, PACK)
    q = _qmd(root, CANON_DOC)
    entry = next(d for d in plan(q, mode="light").dimensions if d.id == "terminology")
    assert entry.covered_by_lint is True


def test_dirty_document_keeps_the_terminology_reviewer(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, PACK)
    q = _qmd(root, FORBIDDEN_DOC)
    entry = next(d for d in plan(q, mode="light").dimensions if d.id == "terminology")
    assert entry.covered_by_lint is False


def test_pack_without_terms_keeps_the_terminology_reviewer(tmp_path):
    root = _git_repo(tmp_path)
    _write_house(root, {"name": "h"})
    q = _qmd(root, CANON_DOC)
    entry = next(d for d in plan(q, mode="light").dimensions if d.id == "terminology")
    assert entry.covered_by_lint is False


def test_cli_json_carries_covered_by_lint(tmp_path, capsys):
    root = _git_repo(tmp_path)
    _write_house(root, PACK)
    q = _qmd(root, CANON_DOC)
    assert plan_main([str(q), "--json"]) == 0
    dims = json.loads(capsys.readouterr().out)["dimensions"]
    term = next(d for d in dims if d["id"] == "terminology")
    assert term["covered_by_lint"] is True
    assert all(set(d) == {"id", "when", "reason", "covered_by_lint"} for d in dims)


