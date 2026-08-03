"""Soft-hyphen line-break artifacts: «невоз-можности», «выполня-лась», «размет-ки».

They come from pasting justified/hyphenated text (a PDF, a Word column). The discriminator
against a legitimate compound is dictionary membership:

    artifact  iff  known(left+right) and not (known(left) and known(right))

«невозможности» is a word and neither half is → artifact. «мастер-модели» is not a word
while both halves are → compound. Measured 7/7 with no false positives on a real editor
review. Without morphology this cannot be decided, so the check falls back to
"this hyphenated form occurs exactly once in the document", which halves precision — hence
the entry demotes itself to `warn` (see `lib.lint_prose._effective_severity`).
"""
from __future__ import annotations
import re
from typing import Iterable

from lib.checks import Hit, register

# Deliberately case-sensitive: a line-break hyphen never capitalises mid-word, so keeping
# it lowercase-only drops «ио-УЗИ», «КТ-АГ» and friends before they reach the decision.
_PAIR = re.compile(r"(?<![\w-])([а-яё]{2,})-([а-яё]{2,})(?![\w-])")


@register("ortho-hyphen-linebreak")
def hyphen_linebreak(doc, morph, entry: dict) -> Iterable[Hit]:
    allow = {w.lower() for w in entry.get("allow", ())}
    if morph.available:
        def decide(left: str, right: str) -> bool:
            return morph.known(left + right) and not (morph.known(left) and morph.known(right))
    else:
        counts = _pair_counts(doc)

        def decide(left: str, right: str) -> bool:
            return counts[f"{left}-{right}"] == 1
    for pl in doc.lines:
        for m in _PAIR.finditer(pl.text):
            left, right = m.group(1).lower(), m.group(2).lower()
            if m.group(0).lower() in allow:
                continue
            if decide(left, right):
                yield Hit(lineno=pl.lineno, col=m.start() + 1, matched=m.group(0),
                          detail=f"слитно: «{left + right}»")


def _pair_counts(doc) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pl in doc.lines:
        for m in _PAIR.finditer(pl.text):
            key = m.group(0).lower()
            counts[key] = counts.get(key, 0) + 1
    return counts
