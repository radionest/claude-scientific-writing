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


def test_error_finding_sets_exit_1(tmp_path):
    from lib.lint_prose import main
    p = tmp_path / "x.qmd"
    p.write_text("референсный стандарт\n", encoding="utf-8")
    assert main([str(p)]) == 1
