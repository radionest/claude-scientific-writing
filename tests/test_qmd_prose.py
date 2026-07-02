from lib.qmd_prose import extract_prose


def _texts(src):
    return [(p.lineno, p.text.strip()) for p in extract_prose(src)]


def test_skips_yaml_front_matter():
    src = "---\ntitle: модальность\n---\nреальная проза\n"
    assert _texts(src) == [(4, "реальная проза")]


def test_skips_fenced_code_chunk():
    src = "до\n```{python}\nx = 'модальность'\n```\nпосле\n"
    assert _texts(src) == [(1, "до"), (5, "после")]


def test_strips_inline_python_and_code_and_citations():
    src = "значение `{python} n` и `code` источник [@smith2020] тут\n"
    # each stripped inline span -> one space; flanking spaces preserved (3 total). Whitespace-insensitive downstream.
    assert _texts(src) == [(1, "значение   и   источник   тут")]


def test_skips_table_rows():
    src = "| метод | модальность |\n|---|---|\nпроза\n"
    assert _texts(src) == [(3, "проза")]


def test_skips_single_and_multiline_html_comments():
    src = "a <!-- модальность --> b\n<!-- начало\nмодальность\nконец -->\nc\n"
    assert _texts(src) == [(1, "a   b"), (5, "c")]


def test_keeps_heading_prose():
    src = "## Оценка модальности\nтекст\n"
    assert _texts(src) == [(1, "## Оценка модальности"), (2, "текст")]


def test_captures_lint_ok_ids_on_line():
    src = "законный референсный тут <!-- lint-ok: calque-referens -->\n"
    prose = extract_prose(src)
    assert prose[0].suppress == {"calque-referens"}
    assert "референсный" in prose[0].text
