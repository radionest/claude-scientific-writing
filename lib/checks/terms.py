"""Term usage that one prose line cannot decide.

«на КТ» is the radiologists' locative («на изображениях») and gets flagged — but the same
string is legitimate when a verb of transfer or reliance governs «на» + винительный:
«перенести на КТ», «распространить анализ на МРТ», «опираются в основном на МРТ». The
governing verb sits one to three tokens back, and Python `re` has no variable-width
lookbehind, so the regex entry flagged all three. Deliberately morphology-free: a generic
"previous token is a VERB" test would silence the жаргон this rule exists for
(«на КТ определяется очаг»), and the hook runs without the extra anyway.
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
