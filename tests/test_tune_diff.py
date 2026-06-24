from lib.lint_prose import load_entries
from lib.tune_diff import diff_prose

ENTRIES = load_entries(None)


def test_no_change_yields_no_hunks():
    src = "Очаги распознавали методами лучевой диагностики.\n"
    assert diff_prose(src, src, ENTRIES) == []


def test_fp_when_edit_trips_a_rule():
    # pristine чист; пользователь уходит к кальке, которую словарь запрещает
    before = "Использовали эталонный стандарт сравнения.\n"
    after = "Использовали референсный стандарт сравнения.\n"
    hunks = diff_prose(before, after, ENTRIES)
    assert len(hunks) == 1
    assert hunks[0].triage == "FP"
    assert hunks[0].rule_hit == "calque-referens"
    assert hunks[0].before_dirty is False


def test_fn_when_replacement_trips_no_rule():
    # 'продемонстрировало' нет в словаре -> FN-кандидат
    before = "Исследование продемонстрировало увеличение очага.\n"
    after = "Исследование показало рост очага.\n"
    hunks = diff_prose(before, after, ENTRIES)
    assert len(hunks) == 1
    assert hunks[0].triage == "FN"
    assert hunks[0].rule_hit is None


def test_pure_deletion_is_neutral():
    before = "Первое предложение.\nВторое предложение.\n"
    after = "Первое предложение.\n"
    hunks = diff_prose(before, after, ENTRIES)
    assert len(hunks) == 1
    assert hunks[0].triage == "neutral"


def test_before_dirty_flags_writer_miss():
    # pristine сам трогает правило (само-линт промахнулся) -> before_dirty True
    before = "Оценивали оба метода визуализации (модальности).\n"
    after = "Оценивали оба метода.\n"
    hunks = diff_prose(before, after, ENTRIES)
    assert len(hunks) == 1
    assert hunks[0].before_dirty is True
    assert hunks[0].triage == "FN"
