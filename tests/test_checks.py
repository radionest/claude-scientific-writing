"""Regressions for false blocks and mis-anchored findings found in pre-PR review."""
import pytest

from lib.lint_prose import lint_source, load_check_entries, load_entries
from lib.morph import Morph

MORPH = Morph.load()
ENTRIES, CHECKS = load_entries(None), load_check_entries()


def _find(text: str):
    return lint_source(text + "\n", ENTRIES, CHECKS, MORPH)


def _ids(text: str, severity: str | None = None):
    return {f.id for f in _find(text) if severity is None or f.severity == severity}


@pytest.mark.parametrize("sentence", [
    "В то время как одни авторы отмечают рост, другие его не находят.",
    "Несмотря на то что выборка мала, различие значимо.",
    "По мере того как доза растёт, чувствительность падает.",
    # a bullet or heading does not stop the clause from being fronted
    "- В то время как одни авторы отмечают рост, другие его не находят.",
    "## Несмотря на то что выборка мала, различие значимо.",
    "1) В случае если объём достаточен, выполняли резекцию.",
    # the comma may equally go before the whole conjunction
    "Чувствительность КТ была выше, в то время как специфичность не различалась.",
    "Резекцию отложили, несмотря на то что риск был низким.",
])
def test_correctly_punctuated_compound_conjunction_is_not_flagged(sentence):
    assert "punct-comma-slozhnyj-soyuz" not in _ids(sentence)


def test_compound_conjunction_without_any_comma_is_flagged():
    ids = _ids("Волюмометрию делали в случае если объём был более 50 %.")
    assert "punct-comma-slozhnyj-soyuz" in ids


def test_compound_conjunction_never_gates():
    """Both placements are correct Russian, so this rule must not block a commit."""
    hits = [f for f in _find("Волюмометрию делали в случае если объём был более 50 %.")
            if f.id == "punct-comma-slozhnyj-soyuz"]
    assert hits and all(f.severity == "warn" for f in hits)


@pytest.mark.parametrize("sentence", [
    "Очаги, в состав которых входит фиброз, исключили из анализа.",   # substring-matched preposition
    "Фазу, в каждый из катетеров которой вводили препарат, сравнили.",
])
def test_kotoryj_not_flagged_when_already_correct(sentence):
    assert "punct-comma-kotoryj" not in _ids(sentence)


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="possessive «который» needs case tags")
def test_kotoryj_skips_genitive_possessive():
    """«…, размеры которых превышали…» — genitive «который» belongs to the preceding noun
    phrase and takes no comma of its own. Only morphology can see the case."""
    assert "punct-comma-kotoryj" not in _ids("Очаги, размеры которых превышали 10 мм, резецировали.")


def test_kotoryj_still_flags_a_missing_comma():
    assert "punct-comma-kotoryj" in _ids("Отметили метастаз который был виден только на МРТ.")


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="needs case tags")
def test_possessive_guard_does_not_silence_a_relative_clause():
    """«пациента которого» agrees in case — an ordinary relative clause that does need the
    comma. Keying the possessive reading on the genitive tag alone muted it."""
    assert "punct-comma-kotoryj" in _ids("Мы описали пациента которого оперировали дважды.")


@pytest.mark.parametrize("sentence", [
    "Однако выборка была мала.",
    "Наконец мы получили результат.",
    "Тем не менее различие сохранялось.",
])
def test_sentence_initial_conjunctions_are_not_parenthetical(sentence):
    """«Однако», «наконец», «тем не менее» opening a sentence are conjunctions and take no
    comma (Rosenthal §25). The rule used to demand one — advising an outright error."""
    assert "punct-comma-vvodnoe" not in _ids(sentence)


@pytest.mark.parametrize("sentence", [
    "Например нанести метку на мастер-модель.",
    "Таким образом чувствительность выросла.",
])
def test_real_parentheticals_still_flagged(sentence):
    assert "punct-comma-vvodnoe" in _ids(sentence)


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="gerund tagging needs morphology")
def test_gerund_guard_survives_markup():
    """A heading or bullet must not make a fronted gerund look mid-sentence."""
    assert "punct-comma-deeprichastie" not in _ids("## Учитывая объём резекции хирург выбрал доступ.")


def test_tak_zhe_comparative_is_not_a_conjunction():
    """«так же …, как» is comparison, not the conjunction «также» — the rule's own message
    says so, but it errored on it anyway."""
    assert "style-takzhe-slitno" not in _ids(
        "Очаги так же исследовались ультразвуковым методом, как и при КТ.")


@pytest.mark.parametrize("sentence", [
    "Каждый очаг так же исследовался ультразвуковым методом.",
    "Удалили метастазы, а так же диагностические очаги.",
])
def test_tak_zhe_as_conjunction_still_errors(sentence):
    assert "style-takzhe-slitno" in _ids(sentence, severity="error")


def test_token_case_tie_claims_no_norm():
    """With equal counts there is no evidence for a canonical spelling; the old tie-break
    sorted uppercase first and reported the correct «3D» as the deviation."""
    findings = [f for f in _find("Строили в 3d Slicer, затем открывали 3D модель заново.")
                if f.id == "doc-token-case"]
    assert {f.matched for f in findings} == {"3d", "3D"}
    assert all("выбери одно написание" in f.message for f in findings)


def test_token_case_flags_every_deviation_not_just_the_first():
    """`--diff` mode keeps only findings on changed lines, so anchoring once would let a
    newly added «3d» through untouched."""
    findings = [f for f in _find(
        "Строили в 3D Slicer. Открывали 3D модель. Смотрели 3D карту. Затем 3d обзор и 3d срез.")
        if f.id == "doc-token-case"]
    assert [f.matched for f in findings] == ["3d", "3d"]
    assert all("приведи к «3D»" in f.message for f in findings)
