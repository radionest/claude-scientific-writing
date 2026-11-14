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


def _p(text):
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
