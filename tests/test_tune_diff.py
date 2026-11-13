import json
import subprocess
from pathlib import Path

import pytest

import lib.lint_prose
from lib.lint_prose import load_check_entries, load_entries
from lib.morph import Morph
from lib.tune_diff import diff_prose, main

ENTRIES = load_entries(None)
CHECKS = load_check_entries()
MORPH = Morph(available=False)


@pytest.fixture(autouse=True)
def _clear_git_cache():
    # `main()` discovers the project-local dictionary at the git root of the edited file;
    # caches are keyed on paths, so drop stale entries between repo-based tests.
    lib.lint_prose._clear_caches()
    yield
    lib.lint_prose._clear_caches()


def test_no_change_yields_no_hunks():
    src = "Очаги распознавали методами лучевой диагностики.\n"
    assert diff_prose(src, src, ENTRIES, CHECKS, MORPH) == []


def test_fp_when_edit_trips_a_rule():
    # pristine чист; пользователь уходит к кальке, которую словарь запрещает
    before = "Использовали эталонный стандарт сравнения.\n"
    after = "Использовали референсный стандарт сравнения.\n"
    hunks = diff_prose(before, after, ENTRIES, CHECKS, MORPH)
    assert len(hunks) == 1
    assert hunks[0].triage == "FP"
    assert hunks[0].rule_hit == "calque-referens"
    assert hunks[0].before_dirty is False


def test_fn_when_replacement_trips_no_rule():
    # 'продемонстрировало' нет в словаре -> FN-кандидат
    before = "Исследование продемонстрировало увеличение очага.\n"
    after = "Исследование показало рост очага.\n"
    hunks = diff_prose(before, after, ENTRIES, CHECKS, MORPH)
    assert len(hunks) == 1
    assert hunks[0].triage == "FN"
    assert hunks[0].rule_hit is None


def test_pure_deletion_is_neutral():
    before = "Первое предложение.\nВторое предложение.\n"
    after = "Первое предложение.\n"
    hunks = diff_prose(before, after, ENTRIES, CHECKS, MORPH)
    assert len(hunks) == 1
    assert hunks[0].triage == "neutral"


def test_before_dirty_flags_writer_miss():
    # pristine сам трогает правило (само-линт промахнулся) -> before_dirty True
    before = "Оценивали оба метода визуализации.\n"
    after = "Оценивали оба метода.\n"
    hunks = diff_prose(before, after, ENTRIES, CHECKS, MORPH)
    assert len(hunks) == 1
    assert hunks[0].before_dirty is True
    assert hunks[0].triage == "FN"


def test_except_is_checked_per_line_not_per_hunk():
    # Multi-line edit: line 1 legitimately uses the `except` token («таргетная терапия»),
    # line 2 has a bare "таргетный" calque. «терапи» on line 1 must NOT suppress the calque on
    # line 2 — `except` is per-line, matching lib.lint_prose (which scans extracted prose by line).
    before = "Очаги сравнивали вручную.\n"
    after = "Таргетная терапия одобрена регулятором.\nТаргетный поиск очагов применяли редко.\n"
    hunks = diff_prose(before, after, ENTRIES, CHECKS, MORPH)
    assert any(h.rule_hit == "calque-targetnyj" for h in hunks)


def test_check_kind_rule_fills_rule_hit():
    # Правка вводит дефект, который ловит kind: "check" (punct-comma-kotoryj). Раньше триаж
    # видел только regex-записи и помечал такую правку FN — кандидатом в новое правило.
    before = "Очаг оставался стабильным.\n"
    after = "Отметили метастаз который сместился за месяц.\n"
    hunks = diff_prose(before, after, ENTRIES, CHECKS, MORPH)
    assert len(hunks) == 1
    assert hunks[0].triage == "FP"
    assert hunks[0].rule_hit == "punct-comma-kotoryj"
    assert hunks[0].before_dirty is False


def test_check_kind_rule_hit_on_before_side():
    # Обратная правка — чинит нарушение проверки в pristine: before_dirty обязан видеть
    # check-kind находку так же, как видит regex-находку.
    before = "Отметили метастаз который сместился за месяц.\n"
    after = "Отметили метастаз, который сместился за месяц.\n"
    hunks = diff_prose(before, after, ENTRIES, CHECKS, MORPH)
    assert len(hunks) == 1
    assert hunks[0].triage == "FN"
    assert hunks[0].rule_hit is None
    assert hunks[0].before_dirty is True


def test_doc_token_case_hit_when_3d_lands_next_to_3D():
    # «3d» рядом с «3D» — находка doc-token-case, которую даёт только целый документ:
    # оба варианта токена не видны одному хунку.
    before = "Модель собрали в 3D Slicer.\n"
    after = "Модель собрали в 3d Slicer, а срезы пересмотрели в 3D.\n"
    hunks = diff_prose(before, after, ENTRIES, CHECKS, MORPH)
    assert len(hunks) == 1
    assert hunks[0].triage == "FP"
    assert hunks[0].rule_hit == "doc-token-case"


LOCAL_RULE = {"id": "local-kalcinatnaya-metka", "layer": "doc", "pattern": "кальцинатн\\w* метк\\w*",
              "severity": "warn", "message": "в проекте: «метка кальцината»"}


def test_local_rule_drives_triage(tmp_path, capsys):
    # Локальный словарь проекта участвует в триаже: правка, которую ловит его правило, —
    # FP, а не FN (иначе tune-learn предложит в canon дубликат уже существующего правила).
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    d = tmp_path / ".claude" / "scientific-writing"
    d.mkdir(parents=True)
    (d / "dictionary.json").write_text(
        json.dumps({"entries": [LOCAL_RULE]}, ensure_ascii=False), encoding="utf-8")
    pristine = tmp_path / "pristine.qmd"
    pristine.write_text("Метки очагов не изменены.\n", encoding="utf-8")
    edited = tmp_path / "edited.qmd"
    edited.write_text("Кальцинатные метки не изменены.\n", encoding="utf-8")
    assert main([str(pristine), str(edited), "--json"]) == 0
    hunks = json.loads(capsys.readouterr().out)
    assert len(hunks) == 1
    assert hunks[0]["triage"] == "FP"
    assert hunks[0]["rule_hit"] == "local-kalcinatnaya-metka"


def test_broken_local_dict_exits_3(tmp_path, capsys):
    # Битый оверлей не должен ронять триаж traceback'ом: exit 3 + stderr с именем файла —
    # как в lint_prose.main.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    d = tmp_path / ".claude" / "scientific-writing"
    d.mkdir(parents=True)
    (d / "dictionary.json").write_text("not json", encoding="utf-8")
    pristine = tmp_path / "pristine.qmd"
    pristine.write_text("Метки очагов не изменены.\n", encoding="utf-8")
    edited = tmp_path / "edited.qmd"
    edited.write_text("Кальцинатные метки не изменены.\n", encoding="utf-8")
    assert main([str(pristine), str(edited)]) == 3
    assert "dictionary.json" in capsys.readouterr().err
