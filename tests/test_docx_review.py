import zipfile

import pytest

from lib.docx_review import DocxError, extract, triage

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _docx(tmp_path, paragraphs, comments):
    """Minimal OOXML: only the parts the extractor reads."""
    body = "".join(paragraphs)
    doc = f'<?xml version="1.0"?><w:document {W}><w:body>{body}</w:body></w:document>'
    cs = "".join(
        f'<w:comment w:id="{cid}" w:author="{author}"><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:comment>'
        for cid, author, text in comments)
    p = tmp_path / "review.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("word/comments.xml", f'<?xml version="1.0"?><w:comments {W}>{cs}</w:comments>')
    return p


def _para(*runs):
    return "<w:p>" + "".join(runs) + "</w:p>"


def _run(text):
    return f"<w:r><w:t>{text}</w:t></w:r>"


def _anchor(cid, text):
    return (f'<w:commentRangeStart w:id="{cid}"/>{_run(text)}'
            f'<w:commentRangeEnd w:id="{cid}"/>')


def test_extracts_comment_with_anchor_and_sentence(tmp_path):
    p = _docx(tmp_path,
              [_para(_run("Врач отметил "), _anchor("1", "очаг"), _run(" на срезе."))],
              [("1", "Редактор", "зпт")])
    items = extract(p)
    assert len(items) == 1
    it = items[0]
    assert it.anchor == "очаг"
    assert it.comment == "зпт"
    assert it.author == "Редактор"
    assert it.sentence == "Врач отметил очаг на срезе."
    assert it.sentence[it.anchor_at:it.anchor_at + len(it.anchor)] == "очаг"


def test_paragraph_numbers_increase(tmp_path):
    p = _docx(tmp_path,
              [_para(_run("Первый абзац целиком.")),
               _para(_run("Второй "), _anchor("1", "абзац"), _run(" тоже."))],
              [("1", "Ред", "убрать")])
    assert extract(p)[0].line == 2


def test_triage_marks_covered_only_on_the_anchor(tmp_path):
    """A rule firing elsewhere in the sentence must not mask a miss — that illusion is
    exactly what made the old dictionary look like it covered a review it did not."""
    p = _docx(tmp_path, [
        _para(_run("Референсный стандарт применяли, "), _anchor("1", "затем"),
              _run(" очаги сопоставляли с макропрепаратом.")),
        _para(_run("Использовали "), _anchor("2", "референсный"), _run(" стандарт сравнения здесь.")),
    ], [("1", "Ред", "зпт"), ("2", "Ред", "калька")])
    by_comment = {i.anchor: i for i in triage(extract(p))}
    assert by_comment["затем"].triage == "FN", "далёкая находка не должна засчитываться"
    assert by_comment["референсный"].triage == "covered"
    assert by_comment["референсный"].rule_hit == "calque-referens"


def test_tracked_changes_become_before_after(tmp_path):
    para = ("<w:p>"
            f'<w:del w:id="9" w:author="Ред"><w:r><w:delText>дооперационной</w:delText></w:r></w:del>'
            f'<w:ins w:id="10" w:author="Ред">{_run("предоперационной")}</w:ins>'
            "</w:p>")
    p = _docx(tmp_path, [para], [])
    items = extract(p)
    assert len(items) == 1
    assert items[0].before == "дооперационной"
    assert items[0].after == "предоперационной"


def test_missing_comments_part_is_not_fatal(tmp_path):
    doc = f'<?xml version="1.0"?><w:document {W}><w:body>{_para(_run("Текст без комментариев."))}</w:body></w:document>'
    p = tmp_path / "plain.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", doc)
    assert extract(p) == []


def test_sentence_survives_an_abbreviation(tmp_path):
    """«и др.» must not end the sentence: `triage` lints this slice, so a truncated
    sentence loses the left context a rule needs and flips covered → FN."""
    p = _docx(tmp_path,
              [_para(_run("Применяли КТ, МРТ и др. методы для оценки "),
                     _anchor("1", "очага"), _run(" в печени."))],
              [("1", "Ред", "уточнить")])
    assert extract(p)[0].sentence == "Применяли КТ, МРТ и др. методы для оценки очага в печени."


def _broken_docx(tmp_path, document_xml, name):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", document_xml)
    return p


def test_dtd_is_refused(tmp_path):
    """`.docx` parts never carry a DOCTYPE, and ElementTree expands internal entities —
    a hostile file could blow memory up before anything reads it."""
    bomb = ('<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">'
            '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
            f'<w:document {W}><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>')
    with pytest.raises(DocxError, match="DTD"):
        extract(_broken_docx(tmp_path, bomb, "bomb.docx"))


def test_malformed_xml_reports_instead_of_crashing(tmp_path):
    """A valid zip whose XML is broken must reach the CLI's friendly message, not a
    traceback — the zip-level guards never see it."""
    with pytest.raises(DocxError, match="XML"):
        extract(_broken_docx(tmp_path, f"<w:document {W}><w:body></w:document>", "torn.docx"))
