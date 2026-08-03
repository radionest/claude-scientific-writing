"""Typos: Russian words the morphology dictionary does not know.

Medical and project vocabulary is legitimately absent from a general dictionary
(«ремнант», «волюмометрия», «макропрепарат»), so this is only usable with a project
wordlist. Put it in the project-local overlay:

    {"id": "ortho-spelling", "allow": ["ремнант", "волюмометрия", "адгезиолизис"]}

Lemmas are matched, so one entry covers every inflected form. Without morphology the
check yields nothing at all.
"""
from __future__ import annotations
import re
from typing import Iterable

from lib.checks import Hit, register

_WORD = re.compile(r"(?<![\w-])[А-Яа-яЁё]{4,}(?![\w-])")


@register("ortho-spelling")
def spelling(doc, morph, entry: dict) -> Iterable[Hit]:
    if not morph.available:
        return
    allow = {w.lower() for w in entry.get("allow", ())}
    allow |= {morph.lemma(w) for w in allow}
    seen: set[str] = set()
    for pl in doc.lines:
        for m in _WORD.finditer(pl.text):
            word = m.group(0)
            low = word.lower()
            if low in allow or morph.lemma(low) in allow or low in seen:
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
