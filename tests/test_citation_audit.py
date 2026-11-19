"""Local citation audit: cited keys vs .bib, duplicate identities, placeholders.
No network, no bibtexparser — a tolerant parser over the raw .bib text."""
from lib.citation_audit import audit, find_bibliography, main, parse_bib

BIB = """@article{ivanov2020,
  title = {Методы сегментации печени},
  doi = {10.1000/ivanov},
}
@article{petrov2021,
  title = {Методы сегментации  печени},
  doi = {10.1000/ivanov},
}
@article{sidorov2022,
  title = {Другая тема},
  pmid = {12345678},
}
@misc{zzz-placeholder,
  title = {TODO fill later},
}
"""


def test_parse_bib_fields_normalized():
    entries = {e.key: e for e in parse_bib(BIB)}
    assert entries["ivanov2020"].doi == "10.1000/ivanov"
    # duplicate-title normalization: case + collapsed whitespace
    assert entries["ivanov2020"].title == entries["petrov2021"].title
    assert entries["sidorov2022"].pmid == "12345678"


def test_audit_findings(tmp_path):
    qmd = tmp_path / "doc.qmd"
    bib = tmp_path / "refs.bib"
    qmd.write_text(
        "---\nbibliography: refs.bib\n---\n\n"
        "Текст с [@ivanov2020] и [-@who2019].\n",
        encoding="utf-8")
    bib.write_text(BIB, encoding="utf-8")
    findings = {(f.category, f.keys) for f in audit(qmd)}
    assert ("missing-key", ("who2019",)) in findings
    assert ("unused-key", ("petrov2021",)) in findings
    assert ("unused-key", ("sidorov2022",)) in findings
    assert ("duplicate-doi", ("ivanov2020", "petrov2021")) in findings
    assert ("duplicate-title", ("ivanov2020", "petrov2021")) in findings
    assert any(f.category == "placeholder-entry" and "zzz-placeholder" in f.keys
               for f in audit(qmd))


def test_no_bibliography_finding(tmp_path):
    qmd = tmp_path / "doc.qmd"
    qmd.write_text("Текст без библиографии [@x].\n", encoding="utf-8")
    findings = audit(qmd)
    assert [f.category for f in findings] == ["no-bibliography"]


def test_sibling_bib_fallback(tmp_path):
    qmd, bib = tmp_path / "doc.qmd", tmp_path / "only.bib"
    qmd.write_text("Текст [@a].\n", encoding="utf-8")
    bib.write_text("@article{a, title = {T}}\n", encoding="utf-8")
    assert find_bibliography(qmd) == [bib]
    assert audit(qmd) == []


def test_yaml_block_list_bibliography(tmp_path):
    qmd = tmp_path / "doc.qmd"
    bibs = [tmp_path / "a.bib", tmp_path / "b.bib"]
    qmd.write_text("---\nbibliography:\n  - a.bib\n  - b.bib\n---\n\nТекст [@a] и [@b].\n",
                   encoding="utf-8")
    for bib, key, title in zip(bibs, "ab", ("Первый", "Второй")):
        bib.write_text(f"@article{{{key},\n  title = {{{title}}}\n}}\n", encoding="utf-8")
    assert find_bibliography(qmd) == bibs
    assert audit(qmd) == []


def test_missing_declared_bib_reports_missing_bib_file(tmp_path):
    qmd = tmp_path / "doc.qmd"
    qmd.write_text("---\nbibliography: gone.bib\n---\n\nТекст [@x].\n", encoding="utf-8")
    findings = audit(qmd)
    assert [f.category for f in findings] == ["missing-bib-file"]
    assert findings[0].keys == (str(tmp_path / "gone.bib"),)


def test_cli_exit_codes(tmp_path):
    qmd, bib = tmp_path / "doc.qmd", tmp_path / "refs.bib"
    qmd.write_text("---\nbibliography: refs.bib\n---\n\nВид [@missing].\n",
                   encoding="utf-8")
    bib.write_text("@article{present, title = {T}}\n", encoding="utf-8")
    assert main([str(qmd), "--json"]) == 1
    assert main([str(tmp_path / "nope.qmd")]) == 2
