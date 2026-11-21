import io
import json
import subprocess
import zipfile

import pytest

from lib.docx_review import DocxError
from lib.lint_prose import load_entries
from lib.render_lint import extract_units, lint_render, main

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
ENTRIES = load_entries(None)  # real canon: calque-referens is error-severity


def _docx(tmp_path, body, name="render.docx"):
    doc = f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>'
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", doc)
    return p


def _p(text, style=None):
    if style:
        return (f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
                f"<w:r><w:t>{text}</w:t></w:r></w:p>")
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _tbl(*rows):
    trs = "".join("<w:tr>" + "".join(f"<w:tc>{_p(t)}</w:tc>" for t in row)
                  + "</w:tr>" for row in rows)
    return f"<w:tbl>{trs}</w:tbl>"


def test_extracts_body_paragraphs_and_table_cells(tmp_path):
    p = _docx(tmp_path, _p("Первый абзац.") + _tbl(("Показатель", "Значение"),
                                                   ("Калька", "референсный стандарт")))
    units = extract_units(p)
    assert [(u.kind, u.text) for u in units] == [
        ("body", "Первый абзац."),
        ("cell", "Показатель"), ("cell", "Значение"),
        ("cell", "Калька"), ("cell", "референсный стандарт"),
    ]
    assert units[4].ref == "tbl1 r2 c2"
    assert units[4].lineno == 5  # document-wide paragraph ordinal


def test_regex_rule_fires_inside_table_cell(tmp_path):
    p = _docx(tmp_path, _tbl(("Признак", "референсный стандарт")))
    hits = lint_render(p, ENTRIES)
    assert hits[0]["id"] == "calque-referens"
    assert hits[0]["unit"] == "tbl1 r1 c2"
    assert hits[0]["matched"] == "референсный"
    assert hits[0]["severity"] == "error"


def test_extracts_units_inside_sdt_container(tmp_path):
    """Word-authored .docx wrap paragraphs/tables in w:sdt content controls (TOC
    field results etc.) — the body walk must descend into containers or those
    units are silently skipped."""
    body = ("<w:sdt><w:sdtPr/><w:sdtContent>"
            + _p("Абзац внутри контейнера.")
            + _tbl(("Признак", "референсный стандарт"))
            + "</w:sdtContent></w:sdt>")
    p = _docx(tmp_path, body)
    units = extract_units(p)
    assert [(u.kind, u.text) for u in units] == [
        ("body", "Абзац внутри контейнера."),
        ("cell", "Признак"), ("cell", "референсный стандарт"),
    ]
    assert units[2].ref == "tbl1 r1 c2"
    hits = lint_render(p, ENTRIES)
    assert hits[0]["id"] == "calque-referens"
    assert hits[0]["unit"] == "tbl1 r1 c2"


def test_qmd_hint_points_into_the_generating_chunk(tmp_path):
    qmd = tmp_path / "doc.qmd"
    qmd.write_text("Проза чистая.\n```{python}\n"
                   "add(\"\", f\"референсный — {n_pct(x)}\")\n```\n", encoding="utf-8")
    p = _docx(tmp_path, _tbl(("x", "референсный — 5 (10 %)")))
    f = lint_render(p, ENTRIES, qmd)[0]
    assert f["qmd"] == "L3 (chunk)"  # prefix "референсный" before the {placeholder}


def test_qmd_hint_fallback_survives_rendered_values(tmp_path):
    """Rendered values never appear verbatim in the source: the fallback probe
    strips the numeric tail but keeps the dash, so the comment distractor
    (bare «не указан», no dash) cannot anchor the hint."""
    qmd = tmp_path / "doc.qmd"
    qmd.write_text("Проза чистая.\n```{python}\n"
                   "# пропуски помечаются «не указан»\n"
                   "add(\"\", f\"не указан — {n_pct(x)}\")\n"
                   "```\n", encoding="utf-8")
    p = _docx(tmp_path, _tbl(("Пол", "не указан — 0 (0%)")))
    f = [h for h in lint_render(p, ENTRIES, qmd)
         if h["id"] == "render-zero-missing-row"][0]
    assert f["qmd"] == "L4 (chunk)"


def test_tilde_fences_are_chunk_boundaries(tmp_path):
    """Quarto accepts ~~~ fences: `_qmd_lines` toggling only on ``` marks the whole
    file as prose, so a finding from a ~~~-fenced chunk loses its (chunk) marker."""
    qmd = tmp_path / "doc.qmd"
    qmd.write_text("Проза чистая.\n~~~{python}\n"
                   "add(\"\", f\"не указан — {n_pct(x)}\")\n"
                   "~~~\n", encoding="utf-8")
    p = _docx(tmp_path, _tbl(("Пол", "не указан — 0 (0%)")))
    f = [h for h in lint_render(p, ENTRIES, qmd)
         if h["id"] == "render-zero-missing-row"][0]
    assert f["qmd"] == "L3 (chunk)"


def test_missing_docx_exits_2_with_friendly_message(tmp_path, capsys):
    """main() guards lint_render with only DocxError/UnicodeDecodeError: a missing
    .docx leaks a FileNotFoundError traceback and exit 1 — the exit table says 2."""
    assert main([str(tmp_path / "nope.docx")]) == 2
    assert "вход не читается" in capsys.readouterr().err


def test_missing_qmd_exits_2(tmp_path, capsys):
    p = _docx(tmp_path, _p("Чистый текст."))
    assert main([str(p), "--qmd", str(tmp_path / "nope.qmd")]) == 2
    assert "вход не читается" in capsys.readouterr().err


def test_clean_docx_yields_no_findings(tmp_path):
    p = _docx(tmp_path, _p("Эталонный стандарт применяли всем пациентам.")
              + _tbl(("Пол", "мужской — 6 (55 %)")))  # NB: space before % — punct-percent-spacing
    assert lint_render(p, ENTRIES) == []


def test_json_flat_array_and_exit_codes(tmp_path, capsys):
    p = _docx(tmp_path, _tbl(("x", "референсный")))
    assert main([str(p), "--json"]) == 1  # error-severity finding -> exit 1
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, list) and out[0]["id"] == "calque-referens"
    clean = _docx(tmp_path, _p("Чистый текст."), name="clean.docx")
    assert main([str(clean), "--json"]) == 0


def test_malformed_xml_reports_instead_of_crashing(tmp_path):
    """A valid zip with torn word/document.xml must raise DocxError, not leak an
    unhandled ExpatError — the zip-level guards never see parser errors."""
    p = tmp_path / "torn.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>")
    with pytest.raises(DocxError, match="XML"):
        extract_units(p)


def test_password_protected_docx_reports_instead_of_crashing(tmp_path, monkeypatch, capsys):
    """zipfile raises a bare RuntimeError when an entry is encrypted; it must reach
    the CLI's friendly message + exit 2, not a traceback."""
    p = _docx(tmp_path, _p("Чистый текст."))

    def refuse(_self, _name):
        raise RuntimeError("File word/document.xml is encrypted, "
                           "password required for extraction")

    monkeypatch.setattr(zipfile.ZipFile, "read", refuse)
    assert main([str(p)]) == 2
    assert "паролем" in capsys.readouterr().err


def test_zero_missing_row_flagged_outcome_zero_not(tmp_path):
    p = _docx(tmp_path, _tbl(("Пол", "не указан — 0 (0%)"),
                             ("Осложнения", "0 (0%)"),
                             ("Статус печени", "не указан — 10 (91%)")))
    hits = [f["id"] for f in lint_render(p, ENTRIES)]
    assert hits.count("render-zero-missing-row") == 1
    assert main([str(p), "--json"]) == 0  # warn-severity: advisory, not an error exit


def test_malformed_overlay_config_error_exit_3(tmp_path, capsys):
    """With --qmd, entries come from the qmd project's overlay: a malformed one must map
    to the documented config contract — exit 3 with `config: <file>: <reason>` on stderr
    (the exit-3 row of text-review's lint table) — not to a traceback or a lint run.
    The .docx is a real file but is never opened: ConfigError fires before extraction."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    overlay_dir = repo / ".claude" / "scientific-writing"
    overlay_dir.mkdir(parents=True)
    (overlay_dir / "dictionary.json").write_text("{", encoding="utf-8")
    qmd = repo / "doc.qmd"
    qmd.write_text("любой текст\n", encoding="utf-8")
    docx = _docx(tmp_path, _p("Чистый текст."))
    assert main([str(docx), "--qmd", str(qmd)]) == 3
    err = capsys.readouterr().err
    assert err.startswith("config:") and "dictionary.json" in err


def test_non_utf8_qmd_is_config_error_exit_3(tmp_path, capsys):
    """lint_render reads the qmd as UTF-8 (`_qmd_lines`): a cp1251 source raises
    UnicodeDecodeError inside lint_render — main() must map it to the config
    contract (exit 3, `config:` prefix), not leak a traceback that lies about
    the contract (1 = error-severity findings)."""
    qmd = tmp_path / "doc.qmd"
    qmd.write_bytes("Исходник в cp1251: референсный стандарт\n".encode("cp1251"))
    p = _docx(tmp_path, _p("Чистый текст."))
    assert main([str(p), "--qmd", str(qmd)]) == 3
    err = capsys.readouterr().err
    assert err.startswith("config:")
    assert str(qmd) in err  # the message names the exact offending path


def test_extracts_paragraph_style(tmp_path):
    p = _docx(tmp_path, _p("Заголовок раздела", "Heading1") + _p("Обычный абзац."))
    units = extract_units(p)
    assert [u.style for u in units] == ["Heading1", ""]


def test_table_sequence_flags_jump_and_duplicate(tmp_path):
    body = (_p("Таблица 1 — Критерии включения")
            + _p("Таблица 3 — Осложнения")
            + _p("Таблица 2 — Сравнение групп")
            + _p("Таблица 2 — Повтор номера"))
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "render-table-sequence"]
    assert len(hits) == 2
    assert all(f["severity"] == "warn" for f in hits)
    assert "пропуск" in hits[0]["message"]
    assert "дубликат" in hits[1]["message"]


def test_ref_target_flags_mention_and_caption_orphans(tmp_path):
    body = (_p("Как показано в табл. 2, различие значимо.")
            + _p("Таблица 1 — Критерии включения"))
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "render-ref-target"]
    assert len(hits) == 2
    assert all(f["severity"] == "warn" for f in hits)
    assert {f["line"] for f in hits} == {1, 2}


def test_heading_level_skip_flagged(tmp_path):
    body = (_p("Отчёт", "Heading1") + _p("Раздел", "Heading2")
            + _p("Подраздел", "Heading4") + _p("Ещё подраздел", "Heading2"))
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "render-heading-levels"]
    assert len(hits) == 1
    assert "Heading4" in hits[0]["message"]


def test_vertical_checks_stay_silent_without_material(tmp_path):
    body = _p("Обычный абзац без подписей и стилей.") + _p("Ещё один абзац.")
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] in {"render-table-sequence", "render-figure-sequence",
                           "render-ref-target", "render-heading-levels"}]
    assert hits == []


def test_ref_target_range_mention_covers_the_chain(tmp_path):
    body = (_p("Как показано в табл. 1–3, различия значимы.")
            + _p("Таблица 1 — Критерии") + _p("Таблица 2 — Осложнения")
            + _p("Таблица 3 — Сравнение групп"))
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "render-ref-target"]
    assert hits == []


def test_english_captions_pair_with_english_mentions(tmp_path):
    body = (_p("As shown in Table 2, the difference is significant.")
            + _p("Table 1 — Criteria") + _p("Table 2 — Complications"))
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "render-ref-target"]
    assert {f["line"] for f in hits} == {2}  # Table 1 is never mentioned


def test_english_and_chain_covers_named_tables(tmp_path):
    body = (_p("Tables 2 and 3 summarize the groups.")
            + _p("Table 1 — Criteria") + _p("Table 2 — Groups")
            + _p("Table 3 — Outcomes"))
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "render-ref-target"]
    assert {f["line"] for f in hits} == {2}  # Tables 2 and 3 are covered by the chain


def test_prose_starting_with_table_word_is_not_a_caption(tmp_path):
    body = (_p("Таблица 2 показывает динамику показателей.")
            + _p("Таблица 1 — Динамика"))
    seq = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
           if f["id"] == "render-table-sequence"]
    assert seq == []  # the prose line is not taken for a caption, no «not starting at 1»
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "render-ref-target"]
    assert {f["line"] for f in hits} == {1, 2}  # prose mentions 2; caption 1 unmentioned


def test_continuation_table_is_not_a_duplicate(tmp_path):
    body = (_p("Таблица 1 — Критерии") + _p("Таблица 1 (продолжение)")
            + _p("Таблица 2 — Осложнения"))
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "render-table-sequence"]
    assert hits == []  # the (продолжение) block carries its own caption, not a dup


def test_missing_body_fails_closed(tmp_path):
    """document.xml without w:body (damaged/foreign file) must raise DocxError and
    exit 2 — the old `body or ()` fallback reported a damaged .docx lint-clean (#96)."""
    p = tmp_path / "headless.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}/>')
    with pytest.raises(DocxError, match="w:body"):
        extract_units(p)
    assert main([str(p)]) == 2


def test_corrupt_deflate_reports_instead_of_crashing(tmp_path):
    """A torn deflate stream raises zlib.error inside z.read(); it must surface as
    a friendly DocxError, not leak a traceback past the except chain (#97)."""
    doc = f'<?xml version="1.0"?><w:document {W}><w:body>{_p("Чистый текст.")}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", doc)
    data = bytearray(buf.getvalue())
    # local header: compressed size at 18-21, name/extra lengths at 26-29 — the
    # compressed payload starts right after; garbling it breaks the deflate stream
    csize = int.from_bytes(data[18:22], "little")
    start = 30 + int.from_bytes(data[26:28], "little") + int.from_bytes(data[28:30], "little")
    for i in range(start, start + csize):
        data[i] ^= 0xFF
    p = tmp_path / "torn_deflate.docx"
    p.write_bytes(data)
    with pytest.raises(DocxError, match="повреждённые"):
        extract_units(p)
    assert main([str(p)]) == 2


def test_strict_ooxml_fails_closed(tmp_path):
    """ISO 29500 Strict namespaces miss every _W lookup: the old body fallback
    silently linted zero units and exited 0 (#98) — now a DocxError demands a resave."""
    doc = ('<?xml version="1.0"?>'
           '<w:document xmlns:w="http://purl.oclc.org/ooxml/wordprocessingml/main">'
           f'<w:body>{_p("Чистый текст.")}</w:body></w:document>')
    p = tmp_path / "strict.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", doc)
    with pytest.raises(DocxError, match="Strict"):
        extract_units(p)
    assert main([str(p)]) == 2


def test_glossed_latin_codes_exempt_in_caption_and_cell(tmp_path):
    """issue #88: in captions/cells a Latin data code decoded by a Russian term
    right beside it — «видимые (visible)» — is legal (the #54 allowance carried
    into the render); a multi-code gloss group is exempt too."""
    body = (_p("Таблица 1 — Категории очагов: видимые (visible), едва заметные (faint)")
            + _tbl(("Категория", "Число"),
                   ("Видимые (visible, faint)", "5 (50 %)")))
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "term-latin-data-code"]
    assert hits == []


def test_bare_latin_code_in_cell_still_flagged(tmp_path):
    """The allowance needs the Russian decoding: a bare code in a cell stays an
    error finding (#88)."""
    p = _docx(tmp_path, _tbl(("Категория", "visible"), ("Число", "5 (50 %)")))
    hits = [f for f in lint_render(p, ENTRIES) if f["id"] == "term-latin-data-code"]
    assert len(hits) == 1
    assert hits[0]["unit"] == "tbl1 r1 c2"


def test_glossed_code_in_body_prose_not_exempt(tmp_path):
    """The exemption is caption/cell-only: body prose must name categories in
    Russian even when a paren gloss decodes the code (#88)."""
    p = _docx(tmp_path, _p("Категории — видимые (visible) и faint — учтены."))
    hits = [f for f in lint_render(p, ENTRIES) if f["id"] == "term-latin-data-code"]
    assert len(hits) == 2


def test_out_of_order_trailing_caption_flagged(tmp_path):
    """issue #100: a late out-of-order caption (1, 3, 4, 2) ends below the running
    max with no duplicate — permutation disorder, its own finding, not «пропуск»."""
    body = (_p("Таблица 1 — Критерии") + _p("Таблица 3 — Осложнения")
            + _p("Таблица 4 — Исходы") + _p("Таблица 2 — Сравнение групп"))
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "render-table-sequence"]
    assert len(hits) == 2
    assert "пропуск" in hits[0]["message"]
    assert "нарушение порядка" in hits[1]["message"]


def test_two_captions_swapped_flagged_as_reorder(tmp_path):
    body = _p("Таблица 2 — Осложнения") + _p("Таблица 1 — Критерии")
    hits = [f for f in lint_render(_docx(tmp_path, body), ENTRIES)
            if f["id"] == "render-table-sequence"]
    assert len(hits) == 2  # «не начинается с 1» + the swap
    assert "нарушение порядка" in hits[1]["message"]
