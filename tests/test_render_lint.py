import json
import zipfile

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


def test_qmd_hint_points_into_the_generating_chunk(tmp_path):
    qmd = tmp_path / "doc.qmd"
    qmd.write_text("Проза чистая.\n```{python}\n"
                   "add(\"\", f\"референсный — {n_pct(x)}\")\n```\n", encoding="utf-8")
    p = _docx(tmp_path, _tbl(("x", "референсный — 5 (10 %)")))
    f = lint_render(p, ENTRIES, qmd)[0]
    assert f["qmd"] == "L3 (chunk)"  # prefix "референсный" before the {placeholder}


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
