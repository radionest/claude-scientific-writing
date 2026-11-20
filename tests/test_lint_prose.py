from lib.lint_prose import lint_text, load_entries

ENTRIES = load_entries(None)


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
