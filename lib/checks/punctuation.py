"""Punctuation rules that need sentence scope, morphology, or both.

Purely lexical punctuation patterns (составные союзы, «так же», тире, слэш, проценты)
are regex entries in `canon/orthography.json` instead. What lives here needs to know
where a sentence starts, or needs a part-of-speech decision.
"""
from __future__ import annotations
import re
from typing import Iterable

from lib.checks import Hit, register

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
# Fronted adverbial heads that do not take a comma when the phrase carries no оборот.
_FRONTED = re.compile(
    r"^\s*(После|Для|При|В\s+рамках|По\s+завершени\w+|В\s+случае|В\s+ходе|В\s+результате"
    r"|С\s+целью|На\s+основании|В\s+процессе|В\s+течение|Во\s+время|В\s+условиях)\s+",
    re.IGNORECASE)
_GERUND_SUFFIX = re.compile(r"(?:[ая]сь|[ая]я|[ыои]в|вши|учи|ючи)$", re.UNICODE)
_COORD = frozenset("но а и или либо однако зато что чтобы тогда как".split())
_CASES = ("nomn", "gent", "datv", "accs", "ablt", "loct")


@register("punct-comma-deeprichastie")
def comma_deeprichastie(doc, morph, entry: dict) -> Iterable[Hit]:
    """Деепричастие/деепричастный оборот not set off by a comma.

    Morphology decides, but only when the gerund reading is the *dictionary* parse:
    a bare GRND tag also fires on «время» and «нодулярная».
    """
    if not morph.available:
        return
    for sent in doc.sentences:
        for m in _WORD.finditer(sent.text):
            word = m.group(0)
            if len(word) < 5 or not _GERUND_SUFFIX.search(word.lower()):
                continue
            if not morph.has_pos(word, "GRND"):
                continue
            left = sent.text[:m.start()].rstrip()
            if not left or left[-1] in ",(«—–-:;":
                continue
            yield Hit(lineno=sent.lineno, col=sent.col + m.start(), matched=word,
                      detail="деепричастный оборот выделяется запятой")


@register("punct-comma-prichastie")
def comma_prichastie(doc, morph, entry: dict) -> Iterable[Hit]:
    """Постпозитивный причастный оборот without a comma: «изображения полученные …».

    Requires the participle to follow the noun it agrees with, to head a phrase of its
    own (≥2 more words before the clause boundary), and the noun not to be governed by a
    preposition — that last filter is what removes «по данным», «к имеющимся», «со сниженными».
    """
    if not morph.available:
        return
    for sent in doc.sentences:
        toks = [(m.group(0), m.start()) for m in _WORD.finditer(sent.text)]
        for i in range(1, len(toks)):
            word, pos = toks[i]
            j = i - 1
            if toks[j][0].lower() == "не" and j > 0:
                j -= 1  # «пациентов не получавших …» — the negation sits inside the оборот
            prev, prev_pos = toks[j]
            if not morph.has_pos(word, "PRTF") or not morph.has_pos(prev, "NOUN"):
                continue
            if "," in sent.text[prev_pos + len(prev):pos]:
                continue
            if not _heads_a_phrase(sent.text, pos + len(word)):
                continue
            if not _agree(morph, prev, word):
                continue
            yield Hit(lineno=sent.lineno, col=sent.col + prev_pos, matched=f"{prev} {word}",
                      detail="причастный оборот в постпозиции выделяется запятой")


@register("punct-comma-fronted-adverbial")
def comma_fronted_adverbial(doc, morph, entry: dict) -> Iterable[Hit]:
    """Comma after a fronted adverbial that does not need one: «После создания модели, врач …».

    Legitimate when the fronted phrase contains its own оборот, so a gerund anywhere before
    the comma suppresses the finding.
    """
    for sent in doc.sentences:
        m = _FRONTED.match(sent.text)
        if not m:
            continue
        rest = sent.text[m.end():]
        comma = rest.find(",")
        if comma < 0 or comma > 70:
            continue
        head = rest[:comma]
        head_words = _WORD.findall(head)
        if not head_words or len(head_words) > 6 or any(c in head for c in ".;:—–("):
            continue
        if morph.available and any(morph.has_pos(w, "GRND") for w in head_words):
            continue  # «Учитывая объём резекции, …» — the оборот earns its comma
        if morph.available and any(morph.has_pos(w, "VERB") for w in head_words):
            continue  # a predicate before the comma means the clause already started:
            #           «Для каждого метода … рассчитывали чувствительность, специфичность»
        after = rest[comma + 1:].lstrip()
        after_words = _WORD.findall(after)
        if not after or not after[0].islower() or not after_words:
            continue
        if after_words[0].lower() in _COORD:
            continue  # «…, но метки сравнивали» — the comma joins clauses
        if _enumeration(morph, head_words[-1], after_words[0]):
            continue  # «Для чувствительности, специфичности, …» — an enumeration
        yield Hit(lineno=sent.lineno, col=sent.col + m.end() + comma,
                  matched=f"{m.group(1)} {head.strip()},",
                  detail="обстоятельство в начале предложения запятой не отделяется")


# «;» is deliberately not a check here. It fired 16 times on a review where the editor
# asked for a comma twice: regex cannot separate the two legitimate uses (перечень рубрик,
# однородные ряды с запятыми внутри) from the calque.
# `skills/writing-russian-academic-prose` § «Точка с запятой» documents both and decides
# with judgment — that is the right owner for it.


def _heads_a_phrase(text: str, after: int) -> bool:
    tail = re.split(r"[,.;:!?()»«—–]", text[after:], maxsplit=1)[0]
    return len(_WORD.findall(tail)) >= 2


def _agree(morph, noun: str, participle: str) -> bool:
    ntag, ptag = morph.top_tag(noun), morph.top_tag(participle)
    numbers = ("sing", "plur")
    same_case = any(c in ntag and c in ptag for c in _CASES)
    same_number = any(n in ntag and n in ptag for n in numbers)
    return same_case and same_number


def _enumeration(morph, left: str, right: str) -> bool:
    """Nouns in the same case on both sides → a homogeneous list, not a clause break.

    Both sides must be nouns: «мастер-модели, тот же врач» shares a case reading with
    «тот», but «тот» opens a new subject rather than continuing a list.
    """
    if not morph.available:
        return False
    if not (morph.has_pos(left, "NOUN") and morph.has_pos(right, "NOUN")):
        return False
    ltag, rtag = morph.top_tag(left), morph.top_tag(right)
    # Case *and* number: «модели» (nomn,plur) and «врач» (nomn,sing) collide on case only,
    # and «…мастер-модели, тот же врач…» is a clause break, not a list.
    same_case = any(c in ltag and c in rtag for c in _CASES)
    same_number = any(n in ltag and n in rtag for n in ("sing", "plur"))
    return same_case and same_number
