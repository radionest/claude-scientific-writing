"""Regressions for false blocks and mis-anchored findings found in pre-PR review."""
import pytest

from lib.lint_prose import lint_file, lint_source, load_check_entries, load_entries, merge_entries
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


@pytest.mark.parametrize("sentence", [
    # a comma opening a subordinate clause is not the fronted adverbial's comma
    "При планировании резекции, когда пропуск очага нежелателен, опираются на оба метода.",
    "Для каждого пациента, если очаг был один, разметку не уточняли.",
    # inline code strips to a space, so the comma ended up hanging after a blank
    "При ней `{python} qn(x)` `{python} q(y)`, не выявленные при КТ, учитывали отдельно.",
    # …and the same gap mid-head, where only morphology used to save the rule
    "Для каждого метода на `{python} q(n)` рассчитывали чувствительность, специфичность и ППЦ.",
])
def test_fronted_adverbial_not_flagged_when_comma_belongs_elsewhere(sentence):
    assert "punct-comma-fronted-adverbial" not in _ids(sentence)


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="short participle tagging needs morphology")
def test_fronted_adverbial_skips_short_participle_predicate():
    """«были» top-parses as the noun «быль», so the clause was only visible through the
    краткое причастие «потеряны»."""
    assert "punct-comma-fronted-adverbial" not in _ids(
        "При замене были бы потеряны метастазы, выявленные только при КТ.")


def test_fronted_adverbial_still_flags_its_own_case():
    assert "punct-comma-fronted-adverbial" in _ids(
        "После создания мастер-модели, врач-рентгенолог проецировал очаги.")


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="participle tagging needs morphology")
@pytest.mark.parametrize("sentence", [
    # «;» separates enumeration items exactly as a comma does
    "Критерии включения: завершённая химиотерапия; планируемая резекция метастазов печени.",
    # «в», «и», «Из» all have a NOUN top parse — letter names, not nouns of the оборот
    "Из включённых очагов пять не выявили ни при КТ, ни при КТ-АГ.",
    "Отсюда следует и предполагаемое клиническое место методики.",
    "Очаг попал в резецируемый фрагмент печени.",
])
def test_prichastie_not_flagged_across_a_clause_break(sentence):
    assert "punct-comma-prichastie" not in _ids(sentence)


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="participle tagging needs morphology")
def test_prichastie_still_flags_a_missing_comma():
    assert "punct-comma-prichastie" in _ids(
        "Врач проецировал очаги на изображения полученные в капиллярную фазу.")


@pytest.mark.parametrize("sentence", [
    "Внутриартериальное контрастирование имеет смысл перенести на КТ.",
    "Чтобы распространить нумерацию на КТ-АГ, очаги проецировали заново.",
    "Работы последнего десятилетия опираются в основном на МРТ и ИОУЗИ.",
    "Анализ нужно распространить на МРТ и ПДКТ.",
    "Метку ставили на КТ-изображениях капиллярной фазы.",
])
def test_na_modalnosti_not_flagged_when_a_verb_governs_na(sentence):
    assert "term-na-modalnosti" not in _ids(sentence)


@pytest.mark.parametrize("sentence", [
    "Метастазы, не видимые на КТ и МРТ, попали на мастер-модель.",
    "Отметили на КТ-АГ очаг в шестом сегменте.",
])
def test_na_modalnosti_still_flags_the_locative(sentence):
    assert "term-na-modalnosti" in _ids(sentence)


def test_instrument_agent_does_not_cross_a_sentence_boundary():
    """«…по данным других методов. Выявляемость…» — two sentences, not an instrument-agent."""
    assert "agent-instrument-detect" not in _ids(
        "Они попали на мастер-модель по данным других методов. Выявляемость очагов приведена в таблице.")


def test_instrument_agent_still_flags_within_a_sentence():
    assert "agent-instrument-detect" in _ids("Методы лучевой диагностики распознавали метастазы.")


def test_repeat_window_allows_the_citation_formula():
    assert "doc-repeat-window" not in _ids(
        "У Park и соавт. охарактеризованы 350 очагов, у Tani и соавт. — 78 очагов.")


def test_repeat_window_canon_allow_exempts_a_short_text():
    """«модель» twice in a short fragment: the document frequency (2) stays under the
    term_frequency threshold, so the exemption comes from the canon allow list."""
    assert "doc-repeat-window" not in _ids("Модель построена, модель перепроверена.")


def test_repeat_window_still_flags_a_word_outside_the_allow_list():
    assert "doc-repeat-window" in _ids("Структура изменена, структура описана.")


def test_repeat_window_overlay_allow_replaces_canon_list():
    """`allow` is a field-wise override: a project overlay replaces the canon list —
    to add a word, the project re-lists the exemptions it wants to keep."""
    checks = merge_entries(CHECKS, [{"id": "doc-repeat-window", "allow": ["метод"]}])
    # «модель» was exempt in canon; the overlay's list dropped it, so the repeat fires…
    assert "doc-repeat-window" in {
        f.id for f in lint_source("Модель построена, модель перепроверена.\n",
                                  ENTRIES, checks, MORPH)}
    # …while the overlay's own word is exempt.
    assert "doc-repeat-window" not in {
        f.id for f in lint_source("Метод выбран, метод описан.\n", ENTRIES, checks, MORPH)}


def test_repeat_window_without_morph_folds_by_the_six_letter_prefix():
    """Without morphology (the hook path) the fold key is the word's first six
    characters: forms sharing them are one token, so a six-letter allow entry covers
    the family, while forms differing within the six letters keep distinct keys."""
    def hits(text: str, allow: list[str]) -> set[str]:
        checks = merge_entries(CHECKS, [{"id": "doc-repeat-window", "allow": allow}])
        return {f.id for f in lint_source(text + "\n", ENTRIES, checks, Morph(available=False))}

    # «пациенты» and «пациентов» share the key «пациен» and fire as a repeat…
    assert "doc-repeat-window" in hits("Пациенты осмотрены, пациентов выписали.", [])
    # …while a single six-character entry exempts the whole family.
    assert "doc-repeat-window" not in hits("Пациенты осмотрены, пациентов выписали.", ["пациен"])
    # forms differing within the six characters keep distinct keys, short («очаг»/
    # «очаги», whole-word keys) or exactly at the cut («печень»/«печени»).
    assert "doc-repeat-window" not in hits("Очаг выявлен, очаги измерены.", [])
    assert "doc-repeat-window" not in hits("Печень визуализирована, печени обработаны.", [])


def test_abbrev_first_use_treats_front_matter_as_its_own_scope():
    """Title and abstract are a separate scope: the body re-expands on its own first use."""
    src = ("**Сравнительная эффективность КТ-АГ и КТ**\n\n"
           "## Аннотация\n\n"
           "**Цель.** Сравнить эффективность КТ и КТ-АГ.\n\n"
           "# Введение\n\n"
           "Основным методом остаётся компьютерная томография (КТ) с контрастированием.\n")
    assert "doc-abbrev-first-use" not in {f.id for f in lint_source(src, ENTRIES, CHECKS, MORPH)}


def test_abbrev_first_use_still_flags_a_late_expansion_in_the_body():
    src = ("# Введение\n\n"
           "Резекцию выполняли под контролем ИОУЗИ.\n\n"
           "Интраоперационное ультразвуковое исследование (ИОУЗИ) проводил хирург.\n")
    assert "doc-abbrev-first-use" in {f.id for f in lint_source(src, ENTRIES, CHECKS, MORPH)}


def test_abbrev_variants_flags_every_deviation_not_just_the_first():
    """`--diff` mode keeps only findings on changed lines, so every occurrence is
    anchored — the dominant spelling too, each with a «преобладает» message."""
    src = ("Контроль на ИОУЗИ. Венозную фазу — на ИОУЗИ. Артерии — тоже на ИОУЗИ.\n"
           "Разметку переносили под контролем ио-УЗИ.\n"
           "Описание вели по протоколу ио-УЗИ.\n")
    findings = [f for f in _find(src) if f.id == "doc-abbrev-variants"]
    assert {f.matched for f in findings} == {"ИОУЗИ", "ио-УЗИ"}
    assert [f.line for f in findings if f.matched == "ио-УЗИ"] == [2, 3]
    # each of the three dominant occurrences on line 1 gets its own anchor
    assert [f.col for f in findings if f.matched == "ИОУЗИ"] == [13, 39, 64]
    assert all("преобладает" in f.message for f in findings if f.matched == "ИОУЗИ")
    assert all("приведи к «ИОУЗИ»" in f.message for f in findings if f.matched == "ио-УЗИ")


def test_abbrev_variants_tie_claims_no_norm():
    """With equal counts there is no evidence for a canonical spelling; the old rule
    silently picked whichever variant happened to be rarest."""
    findings = [f for f in _find("Контроль на ио-УЗИ. Описание вели по протоколу ИОУЗИ.")
                if f.id == "doc-abbrev-variants"]
    assert {f.matched for f in findings} == {"ио-УЗИ", "ИОУЗИ"}
    assert all("выбери одно написание" in f.message for f in findings)


def test_abbrev_first_use_flags_every_bare_use_and_the_expansion():
    """`--diff` mode keeps only findings on changed lines: with a single anchor on the
    expansion line, a newly added bare use slipped through untouched."""
    src = ("# Введение\n\n"
           "Резекцию выполняли под контролем ИОУЗИ.\n\n"
           "Второй этап контролировали тоже на ИОУЗИ.\n\n"
           "Интраоперационное ультразвуковое исследование (ИОУЗИ) проводил хирург.\n")
    findings = [f for f in _find(src) if f.id == "doc-abbrev-first-use"]
    assert [f.line for f in findings] == [3, 5, 7]


def test_abbrev_findings_survive_the_diff_filter(tmp_path):
    """End-to-end through `lint_file` — the hook's path: the finding must land on the
    changed line, not only on the untouched line the old single anchor picked."""
    src = ("Контроль на ИОУЗИ. Венозную фазу — на ИОУЗИ. Артерии — тоже на ИОУЗИ.\n"
           "Разметку переносили под контролем ио-УЗИ.\n"
           "Описание вели по протоколу ио-УЗИ.\n"
           "# Введение\n\n"
           "Резекцию выполняли под контролем ИОУЗИ.\n\n"
           "Второй этап контролировали тоже на ИОУЗИ.\n\n"
           "Интраоперационное ультразвуковое исследование (ИОУЗИ) проводил хирург.\n")
    f = tmp_path / "doc.qmd"
    f.write_text(src, encoding="utf-8")
    variants = lint_file(str(f), ENTRIES, changed={3}, check_entries=CHECKS, morph=MORPH)
    assert [x.line for x in variants if x.id == "doc-abbrev-variants"] == [3]
    first_use = lint_file(str(f), ENTRIES, changed={8}, check_entries=CHECKS, morph=MORPH)
    assert [x.line for x in first_use if x.id == "doc-abbrev-first-use"] == [8]


def test_abbrev_variant_anchor_survives_diff_when_edit_flips_dominance(tmp_path):
    """Issue repro: the untouched line keeps the old spelling, the edit flips dominance —
    the newly introduced spelling becomes dominant, so without an anchor of its own its
    occurrences produce no hits and `--diff` loses the whole inconsistency."""
    src = ("Контроль на ИОУЗИ.\n"
           "Разметку переносили под контролем ио-УЗИ.\n"
           "Описание вели по протоколу ио-УЗИ.\n")
    f = tmp_path / "doc.qmd"
    f.write_text(src, encoding="utf-8")
    findings = lint_file(str(f), ENTRIES, changed={2, 3}, check_entries=CHECKS, morph=MORPH)
    variants = [x for x in findings if x.id == "doc-abbrev-variants"]
    assert [x.line for x in variants] == [2, 3]
    assert all(x.matched == "ио-УЗИ" for x in variants)


def test_token_case_anchor_survives_diff_when_edit_flips_dominance(tmp_path):
    """Issue repro for the rule the issue names second: an edit that makes one
    casing dominant must keep anchors on the changed lines."""
    src = ("Объём считали по протоколу 3d.\n"
           "Разметку вели в режиме 3D.\n"
           "Контроль выполняли в 3D.\n")
    f = tmp_path / "doc.qmd"
    f.write_text(src, encoding="utf-8")
    findings = lint_file(str(f), ENTRIES, changed={2, 3}, check_entries=CHECKS, morph=MORPH)
    cases = [x for x in findings if x.id == "doc-token-case"]
    assert [x.line for x in cases] == [2, 3]
    assert all(x.matched == "3D" for x in cases)


def test_token_case_tie_claims_no_norm():
    """With equal counts there is no evidence for a canonical spelling; the old tie-break
    sorted uppercase first and reported the correct «3D» as the deviation."""
    findings = [f for f in _find("Строили в 3d Slicer, затем открывали 3D модель заново.")
                if f.id == "doc-token-case"]
    assert {f.matched for f in findings} == {"3d", "3D"}
    assert all("выбери одно написание" in f.message for f in findings)


def test_token_case_flags_every_deviation_not_just_the_first():
    """`--diff` mode keeps only findings on changed lines, so every occurrence is
    anchored — the dominant «3D» included, each with a «преобладает» message."""
    findings = [f for f in _find(
        "Строили в 3D Slicer. Открывали 3D модель. Смотрели 3D карту. Затем 3d обзор и 3d срез.")
        if f.id == "doc-token-case"]
    assert {f.matched for f in findings} == {"3D", "3d"}
    assert [f.line for f in findings if f.matched == "3d"] == [1, 1]
    assert all("«3D» преобладает" in f.message for f in findings if f.matched == "3D")
    assert all("приведи к «3D»" in f.message for f in findings if f.matched == "3d")


def _with_spelling_allow(allow: list[str]):
    return merge_entries(CHECKS, [{"id": "ortho-spelling", "allow": allow}])


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="spelling needs morphology")
def test_spelling_allow_one_entry_covers_oov_inflections():
    """Issue repro: the single entry «аблирован» must cover «аблированного» and
    «аблированному» — the guesser lemmatizes out-of-dictionary forms to per-form garbage,
    so the family is unified by stem, not by lemma."""
    checks = _with_spelling_allow(["аблирован"])
    src = "Аблированного узла, аблированному участку и аблированные зоны описали отдельно.\n"
    assert "ortho-spelling" not in {f.id for f in lint_source(src, ENTRIES, checks, MORPH)}


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="spelling needs morphology")
def test_spelling_allow_stem_covers_the_derived_adjective():
    """«абляция» (noun) also exempts «абляционную» — derived adjective, same window."""
    checks = _with_spelling_allow(["абляция"])
    assert "ortho-spelling" not in {f.id for f in lint_source(
        "Абляционную зону контролировали на КТ.\n", ENTRIES, checks, MORPH)}


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="spelling needs morphology")
def test_spelling_allow_hyphenated_entry_covers_the_bare_head():
    """Allowing the compound «пост-абляционной» exempts the bare «абляционную»: the stem
    is taken per hyphen part, so the project no longer re-lists «абляционной» (:522)."""
    checks = _with_spelling_allow(["пост-абляционной"])
    assert "ortho-spelling" not in {f.id for f in lint_source(
        "Абляционную перестройку наблюдали у всех пациентов.\n", ENTRIES, checks, MORPH)}


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="spelling needs morphology")
def test_spelling_allow_still_flags_an_unrelated_oov_word():
    """The stem window must not turn the allow list into a blanket amnesty: an
    out-of-dictionary word outside every allowed family is still reported."""
    checks = _with_spelling_allow(["аблирован"])
    assert "ortho-spelling" in {f.id for f in lint_source(
        "Обнаружен вздрыгопыр.\n", ENTRIES, checks, MORPH)}


def test_spelling_yields_nothing_without_morphology():
    """Without the optional extra the check is silent — no finding can rest on a
    degraded allow match."""
    assert "ortho-spelling" not in {f.id for f in lint_source(
        "Вздрыгопыр аблированного типа.\n", ENTRIES, CHECKS, Morph(available=False))}


# --- Discussion genre checks (issue #53): advisory info tripwires at layer genre:article ---

def _genre_find(text: str, rule: str):
    return [f for f in _find(text) if f.id == rule]


def test_discussion_opening_number_flags_a_numberless_first_paragraph():
    """The genre norm puts a quantified main result into Discussion P1; its absence is
    an info prompt on the first prose paragraph only — later paragraphs are not the tripwire."""
    text = ("# Результаты\n\nЧувствительность составила 92 %.\n\n"
            "# Обсуждение\n\nМы показали, что контроль уточняет взаимоотношения очагов с сосудами.\n\n"
            "Во второй группе разница достигала 18 %.\n")
    hits = _genre_find(text, "genre-discussion-opening-number")
    assert [h.line for h in hits] == [7]
    assert all(h.severity == "info" for h in hits)


def test_discussion_opening_number_stays_silent_when_p1_is_quantified():
    assert not _genre_find(
        "# Обсуждение\n\nМы показали, что чувствительность составила 92 %: контроль уточняет границы очагов.\n",
        "genre-discussion-opening-number")


def test_discussion_opening_number_reads_a_hard_wrapped_paragraph():
    """A hard-wrapped paragraph is one paragraph: the quantification on the second
    physical line must douse the tripwire anchored on the first."""
    wrapped = ("# Обсуждение\n\nМы показали, что контроль уточняет границы очагов:\n"
               "чувствительность составила 92 % при медиане наблюдения 14 месяцев.\n")
    assert not _genre_find(wrapped, "genre-discussion-opening-number")
    split_by_blank = ("# Обсуждение\n\nМы показали, что контроль уточняет границы очагов.\n\n"
                      "Чувствительность составила 92 %.\n")
    assert [h.line for h in _genre_find(split_by_blank, "genre-discussion-opening-number")] == [3]


def test_discussion_span_skips_a_literature_review_heading():
    """«Обзор и обсуждение литературы» is a review chapter, not the IMRAD Discussion —
    none of the genre tripwires may anchor on it."""
    text = "## Обзор и обсуждение литературы\n\nНельзя напрямую переносить данные серии [5].\n"
    assert not _genre_find(text, "genre-discussion-opening-number")
    assert not _genre_find(text, "genre-lit-negation-ending")


def test_genre_checks_stay_silent_without_a_discussion_heading():
    """No «Обсуждение» — no genre scope: formulas and disclaimers elsewhere are not
    the article-profile's Discussion norms."""
    text = ("## Литературный обзор\n\nНельзя напрямую сравнивать эти показатели [@ivanov2019].\n\n"
            "## Ограничения\n\nМалый объём выборки не позволяет исключить смещения.\n\n"
            "## Выводы\n\nМалый объём выборки не позволяет исключить смещения.\n")
    assert not _genre_find(text, "genre-discussion-opening-number")
    assert not _genre_find(text, "genre-lit-negation-ending")
    assert not _genre_find(text, "genre-repeated-disclaimer")


def test_lit_negation_ending_flags_a_citation_paragraph_ended_on_a_refusal():
    text = ("# Обсуждение\n\nЧастота прогресса в нашем ряду была ниже, чем в работе [@smirnov2020]. "
            "Нельзя напрямую сравнивать эти показатели.\n")
    hits = _genre_find(text, "genre-lit-negation-ending")
    assert len(hits) == 1
    assert hits[0].severity == "info"
    assert hits[0].matched.lower().startswith("нельзя")


def test_lit_negation_ending_needs_a_citation_and_the_final_sentence():
    """The norm governs literature-directed paragraphs, not the article's own text; a
    refusal mid-paragraph followed by an interpretation is the correct genre pattern."""
    cited = ("# Обсуждение\n\nЧастота была ниже, чем в работе [@smirnov2020]. "
             "Нельзя исключить недоучёт сроков. Расхождение объясняется более ранним "
             "временем МРТ после абляции.\n")
    uncited = ("# Обсуждение\n\nЧастота была ниже ожидаемой. "
               "Нельзя напрямую сравнивать эти показатели.\n")
    assert not _genre_find(cited, "genre-lit-negation-ending")
    assert not _genre_find(uncited, "genre-lit-negation-ending")


def test_lit_negation_ending_reads_a_hard_wrapped_paragraph():
    """Citation on the first physical line, refusal at the end of the last — one
    paragraph, one hit anchored where the refusal ends it."""
    text = ("# Обсуждение\n\n"
            "Частота локального прогресса оказалась ниже, чем в серии [@smirnov2020],\n"
            "а прямое сравнение проводить нельзя.\n")
    hits = _genre_find(text, "genre-lit-negation-ending")
    assert [h.line for h in hits] == [4]
    assert "1 из 1" in hits[0].message


def test_lit_negation_ending_counts_numbered_refs_and_reports_the_ratio():
    text = ("# Обсуждение\n\n"
            "В нашем ряду было 12 наблюдений, согласующиеся данные получили Иванов и соавт [5].\n\n"
            "Медиана выживаемости уступала серии из работы [7]. Не является прямым аналогом наша когорта.\n\n"
            "Единственный очаг менее сантиметра не контрастировал [9]. Эти ряды несопоставимы по срокам МРТ.\n")
    hits = _genre_find(text, "genre-lit-negation-ending")
    assert len(hits) == 2
    assert "2 из 3" in hits[0].message


def test_lit_negation_ending_stays_silent_on_a_positive_comparison():
    assert not _genre_find(
        "# Обсуждение\n\nМедиана выживаемости в нашем ряду сопоставима с данными [7].\n",
        "genre-lit-negation-ending")


def test_repeated_disclaimer_flags_a_cross_subsection_restatement():
    """The scan stays inside the Discussion span: the norm governs the section's own
    subsections («Реферат»/«Заключение» restatements are genre-mandated, not duplicates)."""
    text = ("## Обсуждение\n\n### Ограничения\n\nМалый объём выборки не позволяет исключить влияние "
            "систематических смещений на полученные оценки.\n\n"
            "### Выводы\n\nМалый объём выборки не позволяет исключить влияние систематических "
            "смещений на итоговые оценки.\n")
    hits = _genre_find(text, "genre-repeated-disclaimer")
    assert [h.line for h in hits] == [9]
    assert "строке 5" in hits[0].message


def test_repeated_disclaimer_ignores_a_restatement_outside_the_discussion():
    """The same duplication «Ограничения» → «Выводы» at the top level of a document
    without «Обсуждение» is the repeats dimension's judgment, not this tripwire."""
    text = ("## Ограничения\n\nМалый объём выборки не позволяет исключить влияние систематических "
            "смещений на полученные оценки.\n\n"
            "## Выводы\n\nМалый объём выборки не позволяет исключить влияние систематических "
            "смещений на итоговые оценки.\n")
    assert not _genre_find(text, "genre-repeated-disclaimer")


def test_repeated_disclaimer_needs_different_subsections_and_a_real_overlap():
    """Same-subsection restatement is the `repeats` dimension's judgment, not a tripwire;
    short sentences never reach the Jaccard gate, a headingless fragment has no span."""
    same_section = ("## Обсуждение\n\n### Ограничения\n\nМалый объём выборки не позволяет исключить "
                    "влияние систематических смещений на полученные оценки.\n\n"
                    "Малый объём выборки не позволяет исключить влияние систематических "
                    "смещений на итоговые оценки.\n")
    different_texts = ("## Обсуждение\n\n### Ограничения\n\nМалый объём выборки не позволяет исключить "
                       "влияние систематических смещений.\n\n"
                       "### Выводы\n\nИнтраоперационный контроль уточняет взаимоотношения "
                       "очагов с сосудами и отвечает на цель исследования.\n")
    short = ("## Обсуждение\n\n### Ограничения\n\nПорог не пройдёт.\n\n### Выводы\n\nПорог не пройдёт.\n")
    headingless = ("Малый объём выборки не позволяет исключить влияние систематических "
                   "смещений на полученные оценки.\n\n"
                   "Малый объём выборки не позволяет исключить влияние систематических "
                   "смещений на итоговые оценки.\n")
    assert not _genre_find(same_section, "genre-repeated-disclaimer")
    assert not _genre_find(different_texts, "genre-repeated-disclaimer")
    assert not _genre_find(short, "genre-repeated-disclaimer")
    assert not _genre_find(headingless, "genre-repeated-disclaimer")


def test_repeated_disclaimer_anchors_every_restatement_on_the_first():
    """Three copies in three subsections yield two hits, both pointing at the original —
    not a pair per combination, which would put two findings on one line."""
    text = ("## Обсуждение\n\n### Ограничения\n\nМалый объём выборки не позволяет исключить влияние "
            "систематических смещений на полученные оценки.\n\n"
            "### Выводы\n\nМалый объём выборки не позволяет исключить влияние систематических "
            "смещений на итоговые оценки.\n\n"
            "### Границы переноса\n\nМалый объём выборки не позволяет исключить влияние "
            "систематических смещений на итоговые оценки.\n")
    hits = _genre_find(text, "genre-repeated-disclaimer")
    assert [(h.line, ) for h in hits] == [(9,), (13,)]
    assert all("строке 5" in h.message for h in hits)


def test_list_marker_mix_is_flagged_on_every_occurrence():
    hits = [f for f in _find("- доступ по сегментам\n* разметка под контролем\n* мобилизация печени\n")
            if f.id == "doc-list-marker-consistency"]
    assert len(hits) == 3
    assert all(f.severity == "warn" for f in hits)


def test_ordered_marker_period_and_paren_is_flagged():
    ids = _ids("1. волюмометрия до резекции\n1) волюмометрия после резекции\n")
    assert "doc-list-marker-consistency" in ids


def test_list_markers_differ_by_level_legitimately():
    text = "- хирургический доступ\n  * разметка под контролем ИОУЗИ\n"
    assert "doc-list-marker-consistency" not in _ids(text)
