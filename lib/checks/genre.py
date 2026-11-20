"""Discussion genre norms of the article profile, as far as they stay countable.

`canon/profiles/article.md` («Обсуждение — содержательные нормы») states the norms;
these checks pin the three that reduce to deterministic counters — an opening paragraph
without a number, literature paragraphs ending on a refusal, one disclaimer restated in
another section. Everything else (own-Results grounding, negative cartography, clinical
implication) needs argument reading and belongs to the `genre` dimension of
`prose-reviewer`. All findings are advisory info: genre conventions vary by journal, a
finding asks to reconsider the paragraph, it does not gate.
"""
from __future__ import annotations
import re
from typing import Iterable, TYPE_CHECKING

from lib.checks import Hit, register
from lib.document import split_sentences

if TYPE_CHECKING:
    from lib.document import Sentence
    from lib.qmd_prose import ProseLine

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# «Обсуждение», «Обсуждение результатов», numbered «7. Обсуждение» — or an English heading.
_DISCUSSION = re.compile(r"\b(?:обсуждени\w*|discussion)\b", re.IGNORECASE)
_NUMBER = re.compile(r"\d")
# Numbered-bracket references survive citation stripping: «[5]», «[5, 12]».
_BRACKET_REF = re.compile(r"\[\d+(?:[,\s]+\d+)*\]")
# Closed formula list: the morphology-free proxy for a negated finite predicate or a
# prohibition. Arbitrary negated verbs need parsing — that judgment belongs to the
# `genre` dimension, a regex broad enough to catch them would flag every honest caveat.
_NEGATIVE_END = re.compile(
    r"(?:нельзя"
    r"|не\s+позволя\w*"
    r"|не\s+явля\w*"
    r"|не\s+заменяет?"
    r"|не\s+может\s+(?:быть|рассматриваться|служить|считаться|являться|интерпретироваться|расцениваться)"
    r"|не\s+следует\s+(?:рассматривать|интерпретировать|трактовать|переносить|экстраполировать|сравнивать|расценивать|считать)"
    r"|не\s+(?:эквивалентн\w*|тождественн\w*|идентичн\w*)"
    r"|несопоставим\w*|не\s+сопоставим\w*"
    r"|не\s+даёт\s+основани\w*"
    r"|некорректн\w*\s+(?:сравнивать|говорить|утверждать|переносить|экстраполировать))",
    re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]{5,}", re.UNICODE)

# Near-duplicate = token-set Jaccard. Inflected forms are different tokens without
# morphology, so the threshold only catches near-verbatim restatements.
_JACCARD = 0.7
_MIN_TOKENS = 4


def _heading_of(pl: ProseLine) -> tuple[int, str] | None:
    """(level, title) when the prose line is a heading — heading lines keep their «#»."""
    m = _HEADING.match(pl.text)
    return (len(m.group(1)), m.group(2).strip()) if m else None


def _discussion_span(doc) -> tuple[int, int] | None:
    """(first, last) line numbers of the Discussion section: from the «Обсуждение»
    heading to the next heading of the same or higher level (subsections stay in)."""
    level = start = None
    for pl in doc.lines:
        h = _heading_of(pl)
        if level is None:
            if h and _DISCUSSION.search(h[1]):
                level, start = h[0], pl.lineno
        elif h and h[0] <= level:
            return (start, pl.lineno - 1)
    return (start, doc.lines[-1].lineno) if level is not None and doc.lines else None


def _in_span(lineno: int, span: tuple[int, int]) -> bool:
    return span[0] < lineno <= span[1]


@register("genre-discussion-opening-number")
def discussion_opening_number(doc, morph, entry: dict) -> Iterable[Hit]:
    """The first prose paragraph under the «Обсуждение» heading names no number.

    The genre norm (5 of 8 benchmark papers) puts aim + quantified main result into the
    opening paragraph; its absence is an info prompt, not a gate — «главный результат
    словами» stays legal, that is why the finding never rises above info.
    """
    span = _discussion_span(doc)
    if span is None:
        return
    for pl in doc.lines:
        if not _in_span(pl.lineno, span):
            continue
        if _heading_of(pl):
            continue  # a subsection heading first: keep looking for the first paragraph
        if not _NUMBER.search(pl.text):
            yield Hit(lineno=pl.lineno, col=1, matched=pl.text[:60])
        return  # only the first prose paragraph is the genre tripwire


@register("genre-lit-negation-ending")
def lit_negation_ending(doc, morph, entry: dict) -> Iterable[Hit]:
    """A citation-bearing paragraph of the Discussion whose final sentence is a refusal.

    The paragraph must carry a citation (`[@key]`, kept as `cited`, or a surviving
    numbered «[5]») — the norm governs literature-directed paragraphs, not the article's
    own conclusions. The aggregate ratio rides in every detail: the genre norm is 0–2
    refusals per section, each followed by a numeric comparison and/or a mechanism.
    """
    span = _discussion_span(doc)
    if span is None:
        return
    total = 0
    hits: list[tuple[ProseLine, Sentence, re.Match[str]]] = []
    for pl in doc.lines:
        if not _in_span(pl.lineno, span) or _heading_of(pl):
            continue
        if not (pl.cited or _BRACKET_REF.search(pl.text)):
            continue
        total += 1
        sents = split_sentences(pl)
        if not sents:
            continue
        last = sents[-1]
        m = _NEGATIVE_END.search(last.text)
        if m:
            hits.append((pl, last, m))
    if not hits:
        return
    ratio = (f"{len(hits)} из {total} литературных абзацев «Обсуждения» заканчиваются "
             f"отказом — жанровая норма 0–2")
    for pl, last, m in hits:
        yield Hit(lineno=pl.lineno, col=last.col + m.start(), matched=m.group(0),
                  detail=f"{ratio}; после отказа — сравнение и причина расхождения")


@register("genre-repeated-disclaimer")
def repeated_disclaimer(doc, morph, entry: dict) -> Iterable[Hit]:
    """One near-verbatim sentence restated in a different section — the cross-section
    disclaimer «say it once» does not see with its same-sentence window.

    Both sentences must sit under different headings (a document without headings is one
    section, so fragment linting stays silent). The hit anchors on the restatement, the
    detail names the original line; every restatement points at the same original — a
    sentence said three times yields two hits, both referencing the first, not a pair
    for every combination.
    """
    originals: list[tuple[frozenset[str], Sentence, str | None]] = []
    section: str | None = None
    for pl in doc.lines:
        h = _heading_of(pl)
        if h:
            section = h[1]
            continue
        for sent in split_sentences(pl):
            toks = frozenset(t.lower() for t in _WORD.findall(sent.text))
            if len(toks) < _MIN_TOKENS:
                continue
            for prev_toks, prev_sent, prev_section in originals:
                union = len(toks | prev_toks)
                if section == prev_section or not union:
                    continue
                if len(toks & prev_toks) / union >= _JACCARD:
                    yield Hit(lineno=sent.lineno, col=sent.col, matched=sent.text[:60],
                              detail=f"почти дословно повторяет предложение на строке "
                                     f"{prev_sent.lineno} — оговорка живёт в одном месте")
                    break  # one anchor per restatement — the first canonical occurrence
            else:
                originals.append((toks, sent, section))
