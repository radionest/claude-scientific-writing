import json, re

import pytest

from lib.lint_prose import lint_file, lint_text, load_check_entries, load_entries
from lib.morph import Morph

ENTRIES = load_entries(None)
CHECKS = load_check_entries()
MORPH = Morph.load()


def _ids(src):
    return sorted({f.id for f in lint_text(src, ENTRIES)})


def test_flags_error_calque():
    assert "calque-harakterizacia" in _ids("высокая характеризация природы очага\n")


def test_except_suppresses():
    assert "calque-targetnyj" not in _ids("таргетная терапия одобрена\n")


def test_lint_ok_suppresses_named_id():
    src = "законный референсный стандарт <!-- lint-ok: calque-referens -->\n"
    assert "calque-referens" not in _ids(src)


def test_does_not_flag_inside_code_chunk():
    src = "```{python}\nx = 'референсный'\n```\n"
    assert _ids(src) == []


def test_severity_present_on_finding():
    fs = lint_text("референсный стандарт\n", ENTRIES)
    assert fs and fs[0].severity == "error"


def test_warn_does_not_imply_error_exit(tmp_path):
    # 'когорта' is warn-only -> exit 0
    from lib.lint_prose import main
    p = tmp_path / "x.qmd"
    p.write_text("пациенты когорты\n", encoding="utf-8")
    assert main([str(p)]) == 0


def test_cohort_design_adjective_is_exempt():
    # issue #23: «когортное исследование» — термин дизайна, не жаргон; (?!н) выводит
    # прилагательное «когортн…» из-под правила
    assert "jargon-kogorta" not in _ids("проведено проспективное когортное исследование\n")
    assert "jargon-kogorta" not in _ids("в когортном анализе такие когортные эффекты редки\n")


def test_cohort_noun_still_flagged():
    # существительное «когорта/когорты» флагуется по-прежнему — но warn с контекстной оговоркой;
    # «когорт» без суффикса (род.п. мн.) — тоже матч: lookahead при пустом хвосте проходит
    assert "jargon-kogorta" in _ids("пациенты когорты прошли обследование\n")
    assert "jargon-kogorta" in _ids("в когорте пациентов с ХОБЛ\n")
    assert "jargon-kogorta" in _ids("сравнили три когорт по исходам\n")


def test_latin_data_code_flagged():
    # issue #54: английские коды категорий данных в русской прозе — ошибка (правка
    # рецензента: «это кодировка данных, нужно название русскими словами»)
    assert "term-latin-data-code" in _ids("число и доля выявленных (visible или faint) очагов\n")
    assert "term-latin-data-code" in _ids("очаги категории not_assessable исключили из анализа\n")
    assert "term-latin-data-code" in _ids("строки not_visible и not visible дают разные исходы\n")


def test_latin_data_code_snake_family_and_boundaries():
    # lookbehind (?<![\w@-]) вместо \b: не матчит хвост crossref-метки (@fig-visible,
    # @tbl-faint — «-»/«@» перед началом матча); «invisible» входит в список,
    # но «invisibility» (иное слово) — нет; not_faint покрыт префиксом
    assert "term-latin-data-code" in _ids("очаги partially_visible учтены отдельно\n")
    assert "term-latin-data-code" in _ids("очаг invisible при контрольной МРТ\n")
    assert "term-latin-data-code" in _ids("зоны not_faint оставлены отдельно\n")
    assert "term-latin-data-code" not in _ids("зона invisibility контраста расширена\n")
    assert "term-latin-data-code" not in _ids("схема на рисунке: @fig-visible и @tbl-faint\n")


def test_latin_data_code_legal_paths():
    # коды законны в чанках (подписи tbl-cap/fig-cap живут в опциях чанка), в
    # inline-коде (вырезается до правил) и снимаются lint-ok по месту
    src = "```{r}\n#| tbl-cap: \"Категории очагов: visible, faint\"\nx <- c('visible', 'faint')\n```\n"
    assert _ids(src) == []
    assert _ids("категория указана как `visible` в таблице 2\n") == []
    assert "term-latin-data-code" not in _ids(
        "видимые (visible) с русской расшифровкой <!-- lint-ok: term-latin-data-code -->\n")


def test_kontrast_truncations_flagged():
    # issue #57: «контрастный контроль» и «контрастная МРТ/КТ» — разговорные усечения
    # «МРТ/КТ с контрастным усилением» (клинический сленг, тот же класс, что «гистология»)
    assert "vulgar-kontrastnyj-kontrol" in _ids("через полгода выполнен контрастный контроль\n")
    assert "vulgar-kontrastnyj-kontrol" in _ids("динамическое наблюдение с контрастным контролем\n")
    assert "vulgar-kontrastnaya-mrt-kt" in _ids("метастазы оценивали по контрастной КТ\n")
    assert "vulgar-kontrastnaya-mrt-kt" in _ids("очаг визуализирован на контрастном МРТ\n")
    # дефис — граница слова: «контрастная КТ-контроль» ловится по «контрастная КТ»
    assert "vulgar-kontrastnaya-mrt-kt" in _ids("выполнена контрастная КТ-контроль брюшной полости\n")


def test_kontrast_legal_terms_not_flagged():
    # issue #57: законная радиологическая лексика пар усечений не образует; ведущий \b
    # не пускает «неконтрастная/бесконтрастная» (нативная техника) — без него это FP
    for src in (
        "введение контрастного вещества усилило демаркацию очага\n",
        "диагноз уточнили с помощью внутривенного контрастирования\n",
        "тип накопления контраст-зависимый\n",
        "гепатоспецифический контраст накапливается в гепатоцитах\n",
        "неконтрастная МРТ паренхимы почек\n",
        "бесконтрастная КТ брюшной полости\n",
        "выполнена МРТ с контрастным усилением\n",
        "контрольная МРТ с контрастным усилением через полгода\n",
    ):
        ids = _ids(src)
        assert "vulgar-kontrastnyj-kontrol" not in ids, src
        assert "vulgar-kontrastnaya-mrt-kt" not in ids, src


def test_kontrast_contrastive_pair_and_wrap_notes():
    # контрастивная пара «нативная и контрастная МРТ» законна, но regex её не отличает:
    # правило warn с оговоркой в message, законный случай гасится lint-ok по месту (canon.md)
    src = "динамику оценивали по нативной и контрастной МРТ\n"
    assert "vulgar-kontrastnaya-mrt-kt" in _ids(src)
    assert "vulgar-kontrastnaya-mrt-kt" not in _ids(
        "динамику оценивали по нативной и контрастной МРТ <!-- lint-ok: vulgar-kontrastnaya-mrt-kt -->\n")
    # канарейка линейной локальности: хард-врап между словами не ловится (как обещает note
    # правила); упадёт, если движок станет абзацно-локальным — тогда обнови note
    assert "vulgar-kontrastnyj-kontrol" not in _ids("последующий контрастный\nконтроль очага\n")


def test_error_finding_sets_exit_1(tmp_path):
    from lib.lint_prose import main
    p = tmp_path / "x.qmd"
    p.write_text("референсный стандарт\n", encoding="utf-8")
    assert main([str(p)]) == 1


def test_degraded_note_prefix_per_tool():
    # issue #44: the note is shared across entry points — the caller names itself, so
    # tune_diff/docx_review do not misattribute it to lint_prose.
    from lib.lint_prose import degraded_note, load_check_entries
    checks = load_check_entries(None)
    assert degraded_note(checks, tool="lint_prose").startswith("lint_prose: без морфологии")
    assert degraded_note(checks, tool="tune_diff").startswith("tune_diff: без морфологии")
    assert degraded_note(checks, tool="docx_review").startswith("docx_review: без морфологии")


# -- Seeding contract (issue #25): canon marks `seed: "allow"` on the rules whose
# -- wordlist is the sink for a document's terms; the diff path enforces it.

_UNSEEDED_DOC = "Выполнили аблированного контроль очагов.\n"


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="ortho-spelling needs morphology")
def test_diff_escalates_unseeded_term_to_warn(tmp_path):
    """A term on a changed line was introduced by this edit, so an unseeded one stops
    being advisory: one step up to warn, where the self-lint loops must disposition it.
    A whole-file run keeps info — bulk noise stays cheap."""
    p = tmp_path / "doc.qmd"
    p.write_text(_UNSEEDED_DOC, encoding="utf-8")
    full = lint_file(str(p), ENTRIES, check_entries=CHECKS, morph=MORPH)
    assert [f.severity for f in full if f.id == "ortho-spelling"] == ["info"]
    diff = lint_file(str(p), ENTRIES, changed={1}, check_entries=CHECKS, morph=MORPH)
    assert [f.severity for f in diff if f.id == "ortho-spelling"] == ["warn"]


def test_diff_escalates_only_seeded_rules(tmp_path):
    """The escalation keys off the canon marker, not the severity level: a plain info
    rule without the marker must stay info in the diff path. (The demoted-check-kind
    side of this is pinned by test_diff_does_not_escalate_in_degraded_mode.)"""
    entry = {"id": "style-info-x", "pattern": "преамбул", "severity": "info",
             "message": "m", "layer": "universal",
             "_rx": re.compile("преамбул", re.IGNORECASE | re.UNICODE)}
    p = tmp_path / "doc.qmd"
    p.write_text("В преамбуле методики уточним критерии.\n", encoding="utf-8")
    fs = lint_file(str(p), [entry], changed={1}, check_entries=[], morph=MORPH)
    assert [f.severity for f in fs if f.id == "style-info-x"] == ["info"]


def test_diff_does_not_escalate_in_degraded_mode(tmp_path):
    """Without morphology the hook path runs demoted — escalation must not undo a
    `severity_without_morph` demotion on a seed-marked rule. The demotion lives on
    check-kind entries (`run_checks`), so the seed marker rides one here."""
    entry = {"id": "doc-repeat-window", "kind": "check", "layer": "universal",
             "severity": "warn", "severity_without_morph": "info",
             "message": "повтор", "seed": "allow"}
    p = tmp_path / "doc.qmd"
    p.write_text("С использованием планшета с использованием коагулятора.\n", encoding="utf-8")
    fs = lint_file(str(p), [], changed={1}, check_entries=[entry],
                   morph=Morph(available=False))
    assert [f.severity for f in fs if f.id == "doc-repeat-window"] == ["info"]


def test_seeded_warn_rule_never_escalates_to_error(tmp_path):
    """doc-abbrev-variants carries the contract too but starts at warn — the escalation
    is one step, never into gate territory."""
    src = ("Контроль на ИОУЗИ.\n"
           "Разметку переносили под контролем ио-УЗИ.\n")
    p = tmp_path / "doc.qmd"
    p.write_text(src, encoding="utf-8")
    fs = lint_file(str(p), ENTRIES, changed={1, 2}, check_entries=CHECKS, morph=MORPH)
    assert {f.severity for f in fs if f.id == "doc-abbrev-variants"} == {"warn"}


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="ortho-spelling needs morphology")
def test_unseeded_reports_counts_per_rule(tmp_path, capsys):
    """The issue's minimum: an unseeded-words count per seeding rule that a workflow
    must disposition. Counts are findings, so ortho-spelling's one-per-distinct-word
    dedup shows as 1."""
    from lib.lint_prose import main
    p = tmp_path / "doc.qmd"
    p.write_text("Выполнили аблированного контроль очагов. Некротизированной ткани избегали.\n",
                 encoding="utf-8")
    assert main([str(p), "--unseeded"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"ortho-spelling"}
    assert out["ortho-spelling"] == {"аблированного": 1, "некротизированной": 1}


@pytest.mark.morph
@pytest.mark.skipif(not MORPH.available, reason="ortho-spelling needs morphology")
def test_unseeded_empty_after_seeding(tmp_path, capsys):
    """Disposition closes the report: seeding the word into the overlay's `allow`
    empties it — the verification step /init-doc-spec step 6 relies on."""
    from lib.lint_prose import main
    p = tmp_path / "doc.qmd"
    p.write_text(_UNSEEDED_DOC, encoding="utf-8")
    local = tmp_path / "local.json"
    local.write_text(json.dumps(
        {"entries": [{"id": "ortho-spelling", "allow": ["аблированного"]}]}), encoding="utf-8")
    assert main([str(p), "--unseeded", "--local-dictionary", str(local)]) == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_unseeded_and_json_are_exclusive(tmp_path):
    from lib.lint_prose import main
    p = tmp_path / "doc.qmd"
    p.write_text("Просто текст.\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        main([str(p), "--json", "--unseeded"])
    assert e.value.code == 2
