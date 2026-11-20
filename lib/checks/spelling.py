"""Typos: Russian words the morphology dictionary does not know.

Medical and project vocabulary is legitimately absent from a general dictionary
(«ремнант», «волюмометрия», «макропрепарат»), so this is only usable with a project
wordlist. Put it in the project-local overlay:

    {"id": "ortho-spelling", "allow": ["ремнант", "волюмометрия", "адгезиолизис"]}

One entry covers the whole word family. A word the dictionary knows matches by lemma;
everything else — the usual project term — the guesser lemmatizes to per-form garbage
(«аблированные», «аблированного» never fold to one lemma), so the family is unified by a
six-letter stem instead, taken per hyphen part: allowing «пост-абляционной» also covers
the bare «абляционную». Without morphology the check yields nothing at all.
"""
from __future__ import annotations
import re
from typing import Iterable

from lib.checks import Hit, register

_WORD = re.compile(r"(?<![\w-])[А-Яа-яЁё]{4,}(?![\w-])")

# Letters kept of a stem — the same window the degraded `doc-repeat-window` key uses.
_STEM_LEN = 6


def _stem(w: str) -> str:
    """Six-letter stem, ё folded: the forms of one lexeme (and its derived adjectives)
    share the window; so do same-root strangers («гепатотропный» beside an allowed
    «гепатогенный») — an accepted cost, the root family is what a project allows."""
    return w.replace("ё", "е")[:_STEM_LEN]


@register("ortho-spelling", needs_morph=True)
def spelling(doc, morph, entry: dict) -> Iterable[Hit]:
    if not morph.available:
        return
    allow = {w.lower() for w in entry.get("allow", ())}
    allow |= {morph.lemma(w) for w in allow if morph.known(w)}
    stems = {_stem(p) for w in allow for p in w.split("-")}
    seen: set[str] = set()
    for pl in doc.lines:
        for m in _WORD.finditer(pl.text):
            word = m.group(0)
            low = word.lower()
            if low in allow or morph.lemma(low) in allow or _stem(low) in stems or low in seen:
                continue
            if word.isupper() or (word[0].isupper() and not _sentence_initial(pl.text, m.start())):
                continue  # proper nouns and abbreviations are out of scope
            if morph.known(low):
                continue
            seen.add(low)
            yield Hit(lineno=pl.lineno, col=m.start() + 1, matched=word,
                      detail="нет в словаре — опечатка или термин для проектного словника")


_INITIALS = re.compile(r"(?:[А-ЯЁ]\.\s*){1,3}$")


def _sentence_initial(text: str, pos: int) -> bool:
    """A capitalised word is only sentence-initial if what precedes it really ends a
    sentence. «С.С. Багненко» must not qualify, or every surname reads as a typo."""
    left = text[:pos].rstrip()
    if not left or _INITIALS.search(text[:pos]):
        return not left
    return left[-1] in ".!?:»\"'"
