"""Revision guard: artifact deltas stop scoped edits; rephrase passes. Meaning stays
out of scope on purpose — the rewrite gold set pins that boundary (see Task 7)."""
import json
from collections import Counter
from pathlib import Path

from lib.revision_guard import (CONTINUE, MAX_SUBSTANTIVE_ROUNDS, STOP_OVERHARDENING,
                                STOP_ZERO_EDIT, EditState, GuardFinding, compare, main,
                                next_state, number_keys)

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


def test_percent_on_range_binds_to_both_endpoints():
    assert compare("Давление варьировало 45–79 % от нормы.\n",
                   "Давление варьировало от 45 % до 79 % от нормы.\n") == []
    f = compare("Давление варьировало 45–79 % от нормы.\n",
                "Давление варьировало 45–79 от нормы.\n")
    assert ("number", "changed", "45%") in flat(f)
    assert ("number", "changed", "79%") in flat(f)


def test_four_digit_year_change_is_reported():
    f = compare("Исследование проведено в 2020 году.\n",
                "Исследование проведено в 2021 году.\n")
    assert GuardFinding("number", "changed", "2020", "2020", "2021") in f


def test_period_endpoints_both_reported():
    f = compare("Наблюдение 2020–2024 гг.\n", "Наблюдение 2021–2025 гг.\n")
    assert ("number", "changed", "2020") in flat(f)
    assert ("number", "changed", "2024") in flat(f)


def test_year_typography_equivalence_passes():
    f = compare("Год публикации: 2020.\n", "Год публикации: 2 020.\n")
    assert f == []


def test_thousands_separator_equivalence_passes():
    f = compare("Объём выборки 10 000 записей.\n", "Объём выборки 10000 записей.\n")
    assert f == []


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


def test_cli_clean_diff_exits_zero(tmp_path):
    p = tmp_path / "same.qmd"
    p.write_text("Значение 78 %.\n", encoding="utf-8")
    assert main([str(p), str(p), "--json"]) == 0


# --- gold pins (rewrite-cases.json, frozen by PR-1) ---

CASES = json.loads(
    (ROOT / "tests" / "eval" / "rewrite-cases.json").read_text(encoding="utf-8"))["cases"]
ARTIFACT_DAMAGE = {"citation-key", "code-preserved"}


def test_gold_set_sizes():
    assert len(CASES) == 18


def test_guard_on_rewrite_gold():
    """The guard sees artifact damage, stays silent on clean rephrase AND on semantic
    damage: a token diff neither certifies nor detects meaning. Semantic pairs are the
    fidelity reviewer's job — pinning their silence here keeps that boundary honest."""
    for case in CASES:
        findings = compare(case["before"] + "\n", case["after"] + "\n")
        if case["expect"] == "clean":
            assert findings == [], (case["id"], findings)
        elif case["dimension"] in ARTIFACT_DAMAGE:
            assert findings, f"{case['id']}: artifact damage must be flagged"
        else:
            assert findings == [], (case["id"], findings)


# --- the /text-edit stop rule: three verdicts, at most two substantive rounds ---

BEFORE, AFTER = "Было 78 %.\n", "Стало 87 %.\n"


def test_first_substantive_round_continues():
    assert next_state(BEFORE, AFTER, EditState(rounds=0)) == CONTINUE


def test_second_substantive_round_is_still_admitted():
    assert next_state(BEFORE, AFTER, EditState(rounds=1)) == CONTINUE


def test_third_substantive_round_stops_as_overhardening():
    assert next_state(BEFORE, AFTER, EditState(rounds=2)) == STOP_OVERHARDENING
    assert MAX_SUBSTANTIVE_ROUNDS == 2


def test_zero_edit_stops_at_any_round_budget():
    assert next_state(BEFORE, BEFORE, EditState(rounds=0)) == STOP_ZERO_EDIT
    assert next_state(BEFORE, BEFORE, EditState(rounds=1)) == STOP_ZERO_EDIT
    # zero edit outranks the round limit: nothing was done, over-hardening is moot
    assert next_state(BEFORE, BEFORE, EditState(rounds=2)) == STOP_ZERO_EDIT
