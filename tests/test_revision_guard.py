"""Revision guard: artifact deltas stop scoped edits; rephrase passes. Meaning stays
out of scope on purpose — the rewrite gold set pins that boundary (see Task 7)."""
import json
from collections import Counter
from pathlib import Path

from lib.revision_guard import GuardFinding, compare, main, number_keys

ROOT = Path(__file__).resolve().parents[1]


def flat(findings):
    return [(f.category, f.action, f.key) for f in findings]


def test_number_swap_is_changed():
    f = compare("Чувствительность составила 78 %.\n",
                "Чувствительность составила 87 %.\n")
    assert GuardFinding("number", "changed", "78%", "78%", "87%") in f


def test_lost_repetition_is_a_finding_not_set_stability():
    assert number_keys("Индекс 78, повтор 78.\n") == Counter({"78": 2})
    f = compare("Индекс 78, повтор 78.\n", "Индекс 78.\n")
    assert ("number", "removed", "78") in flat(f)


def test_range_rephrase_passes():
    f = compare("Медиана возраста составила 62 года (интервал 45–79 лет).\n",
                "Медиана возраста больных составила 62 года при диапазоне "
                "от 45 до 79 лет.\n")
    assert f == []


def test_percent_is_bound_to_the_number():
    f = compare("Чувствительность 92 %.\n", "Чувствительность 92.\n")
    assert GuardFinding("number", "changed", "92%", "92%", "92") in f


def test_russian_decimal_comma_and_sign():
    assert number_keys("p = 0,031; сдвиг −5 мм.\n") == Counter({"0.031": 1, "-5": 1})


def test_numbers_inside_citations_and_code_are_masked():
    assert number_keys("По данным [@ivanov2020] p = 0,031.\n") == Counter({"0.031": 1})


def test_citation_key_removal():
    f = compare("По данным мета-анализа [@ivanov2020], чувствительность превышает 90 %.\n",
                "По данным мета-анализа, чувствительность превышает 90 %.\n")
    assert [x for x in f if x.category == "citation-key"] == [
        GuardFinding("citation-key", "removed", "ivanov2020", "ivanov2020", "")]


def test_inline_python_change():
    f = compare("Рассчитывали как `{python}remainder - tumor` и выражали в см³.\n",
                "Рассчитывали как `{python}remainder + tumor` и выражали в см³.\n")
    assert any(x.category == "code" and x.action == "changed" for x in f)


def test_crossref_removal():
    f = compare("Данные сведены в таблицу (@tbl-main).\n",
                "Данные сведены в таблицу.\n")
    assert ("crossref", "removed", "@tbl-main") in flat(f)


def test_url_damage_is_reported():
    before = "Протокол описан ранее: https://doi.org/10.1000/abc\n"
    f = compare(before, "Протокол описан ранее.\n")
    assert flat(f) == [("url", "removed", "https://doi.org/10.1000/abc")]
    assert compare(before, before) == []


def test_frozen_wording_count_change():
    f = compare("методом эталонной модели\nметодом эталонной модели\n",
                "методом эталонной модели\n",
                frozen=["методом эталонной модели"])
    assert GuardFinding("frozen", "changed", "методом эталонной модели", "2", "1") in f


def test_cli_json_and_exit_codes(tmp_path):
    b, a = tmp_path / "b.qmd", tmp_path / "a.qmd"
    b.write_text("Было 78 %.\n", encoding="utf-8")
    a.write_text("Было 87 %.\n", encoding="utf-8")
    assert main([str(b), str(a), "--json"]) == 1
    assert main([str(tmp_path / "missing.qmd"), str(a)]) == 2
