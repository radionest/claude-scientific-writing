import pytest

from lib.morph import Morph

morph = Morph.load()
needs_morph = pytest.mark.skipif(not morph.available, reason="optional morph extra not installed")


def test_unavailable_morph_answers_dont_know():
    off = Morph(available=False)
    assert off.known("очаг") is False
    assert off.has_pos("ориентируясь", "GRND") is False
    assert off.top_is_dictionary("очаг") is False
    assert off.top_tag("очаг") == ""
    assert off.lemma("Очаги") == "очаги"


@needs_morph
@pytest.mark.morph
def test_known_separates_words_from_nonwords():
    assert morph.known("очаг")
    assert morph.known("невозможности")
    assert not morph.known("вздрыгопыр")
    assert not morph.known("можности")


@needs_morph
@pytest.mark.morph
def test_known_tolerates_yo_written_as_e():
    """The DAWG is ё-strict; the parser fallback must cover the common е-spelling."""
    assert morph.known("включённых")
    assert morph.known("включенных")


@needs_morph
@pytest.mark.morph
def test_has_pos_rejects_guessed_parses():
    """Bare POS tags read «время» as GRND — the dictionary-top filter is what makes
    the gerund and participle comma rules usable."""
    assert morph.has_pos("ориентируясь", "GRND")
    assert morph.has_pos("учитывая", "GRND")
    assert not morph.has_pos("время", "GRND")
    assert not morph.has_pos("нодулярная", "GRND")
    assert morph.has_pos("полученные", "PRTF")
    assert not morph.has_pos("данным", "PRTF")


@needs_morph
@pytest.mark.morph
def test_lemma_normalises():
    assert morph.lemma("очаги") == "очаг"
    assert morph.lemma("выполнялась") == "выполняться"
