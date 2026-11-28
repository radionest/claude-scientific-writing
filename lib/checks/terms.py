"""Term usage that one prose line cannot decide.

«на КТ» is the radiologists' locative («на изображениях») and gets flagged — but the same
string is legitimate when a verb of transfer or reliance governs «на» + винительный:
«перенести на КТ», «распространить анализ на МРТ», «опираются в основном на МРТ». The
governing verb sits one to three tokens back, and Python `re` has no variable-width
lookbehind, so the regex entry flagged all three. Deliberately morphology-free: a generic
"previous token is a VERB" test would silence the жаргон this rule exists for
(«на КТ определяется очаг»), and the hook runs without the extra anyway.

`doc-term-canon` and `doc-term-caution` read their terms from the rule record
(`entry["terms"]`): `effective_entries` replaces the canon demo list — the bad/good
oracle needs data to trip — with the project pack's terms, so without a pack
(`<git-root>/.claude/scientific-writing/house.json`) both stay silent.
"""
from __future__ import annotations
import re
from typing import Iterable

from lib.checks import Hit, register

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_METHOD = re.compile(
    r"\bна\s+(?:КТ-АГ|КТ|МРТ|ПЭТ|УЗИ|ПДКТ)\b"
    r"(?!\s*[-–—]?\s*(?:изображени|снимк|томограмм|срез|модел|архив))",
    re.IGNORECASE)
# Verbs that take «на» + винительный: the phrase names a target, not a place of seeing.
_GOVERNING = ("опира", "перенес", "перенос", "распростран", "проецир", "ссыла",
              "ориентир", "замен")
_LOOKBACK = 3


@register("term-na-modalnosti")
def na_modalnosti(doc, morph, entry: dict) -> Iterable[Hit]:
    for sent in doc.sentences:
        for m in _METHOD.finditer(sent.text):
            if _governed(sent.text[:m.start()]):
                continue
            yield Hit(lineno=sent.lineno, col=sent.col + m.start(), matched=m.group(0))


def _governed(head: str) -> bool:
    return any(w.lower().startswith(_GOVERNING) for w in _WORD.findall(head)[-_LOOKBACK:])


def _phrase_rx(phrase: str) -> re.Pattern[str]:
    # A synonym matches as a word start («модель-эталон» covers «модель-эталону»), the
    # same family convention the canon calque patterns use; a hyphen before the phrase
    # is a word-internal joint, not a boundary.
    return re.compile(r"(?<![\w-])" + re.escape(phrase) + r"\w*", re.IGNORECASE | re.UNICODE)


@register("doc-term-canon")
def term_canon(doc, morph, entry: dict) -> Iterable[Hit]:
    """A forbidden synonym of a pack term — the canonical name goes into the detail."""
    for term in entry.get("terms", ()):
        for bad in term.get("forbidden", ()):
            rx = _phrase_rx(bad)
            for pl in doc.lines:
                for m in rx.finditer(pl.text):
                    yield Hit(lineno=pl.lineno, col=m.start() + 1, matched=m.group(0),
                              detail=f"канон проекта — «{term.get('canonical', '')}»")


@register("doc-term-caution")
def term_caution(doc, morph, entry: dict) -> Iterable[Hit]:
    """A variant the project allows with reservations — the term's note in the detail."""
    for term in entry.get("terms", ()):
        note = term.get("note") or f"канон проекта — «{term.get('canonical', '')}»"
        for soft in term.get("caution", ()):
            rx = _phrase_rx(soft)
            for pl in doc.lines:
                for m in rx.finditer(pl.text):
                    yield Hit(lineno=pl.lineno, col=m.start() + 1, matched=m.group(0),
                              detail=note)
