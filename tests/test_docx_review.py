import zipfile

from lib.docx_review import extract, triage

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
