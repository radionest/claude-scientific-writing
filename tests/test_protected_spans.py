"""Protected-span extraction: the raw view the fidelity layer compares. qmd_prose
strips these elements to lint clean prose; revision fidelity needs the spans
themselves, original offsets kept."""
import textwrap

from lib.protected_spans import citation_keys, extract_spans, normalize

SRC = textwrap.dedent("""\
    ---
    title: Тест
    bibliography: refs.bib
    ---

    По данным мета-анализа [@ivanov2020; -@who2019], чувствительность превышает 90 %
    (таблица @tbl-main, рис. @fig-abc). Объём считают как `{python}v - tumor` и
    смотрят <https://example.org/a> и https://doi.org/10.1000/x.

    ```{python}
    # [@notACitation] inside code
    v = 78
    ```

    <!-- lint-ok: calque-x --> HTML-комментарий.
    """)


def spans_of(category: str):
    return [s for s in extract_spans(SRC) if s.category == category]


def test_yaml_frontmatter_is_first_span():
    spans = extract_spans(SRC)
    assert spans[0].category == "yaml"
    assert "bibliography" in spans[0].text


def test_inline_python_wins_over_inline_code():
    py = spans_of("inline-python")
    assert len(py) == 1 and py[0].text == "`{python}v - tumor`"
    assert not [s for s in spans_of("inline-code") if s.start == py[0].start]


def test_citation_inside_fenced_code_is_not_a_citation():
    fenced = spans_of("fenced-code")
    assert len(fenced) == 1
    assert "[@notACitation]" in fenced[0].text
    assert not any("notACitation" in s.text for s in spans_of("citation"))


def test_crossrefs_and_urls_extracted():
    assert {s.text for s in spans_of("crossref")} == {"@tbl-main", "@fig-abc"}
    assert any(s.text.startswith("https://doi.org/") for s in spans_of("url"))
    assert any(s.text.startswith("https://example.org/") for s in spans_of("url"))


def test_url_span_stops_before_trailing_punctuation():
    src = "См. https://example.org/x. Также <https://example.org/y> и (doi.org/10.1/z).\n"
    urls = [s.text for s in extract_spans(src) if s.category == "url"]
    assert urls == ["https://example.org/x", "https://example.org/y",
                    "doi.org/10.1/z"]


def test_offsets_point_into_the_source():
    s = spans_of("inline-python")[0]
    assert SRC[s.start:s.end] == s.text


def test_normalized_squeezes_whitespace_and_unifies_dashes():
    assert normalize("92\u00A0%—x") == "92 %-x"
    assert normalize("a   b") == "a b"


def test_citation_keys_include_suppressed_form():
    assert citation_keys(SRC) == ["ivanov2020", "who2019"]
