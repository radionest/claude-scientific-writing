"""Punctuation rules that need sentence scope, morphology, or both.

Purely lexical punctuation patterns («так же», тире, слэш, проценты) are regex entries in
`canon/orthography.json` instead. What lives here needs to know
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
_CLAUSE_BREAK = re.compile(r"[,;:()«»—–]")
_COORD = frozenset("но а и или либо однако зато что чтобы тогда как".split())
# Subordinators: the comma opens a clause of its own, so it is not the adverbial's comma.
_SUBORD = frozenset("""
когда если где куда пока поскольку хотя чем кто чей
который которая которое которые которого которой которых которым которыми которую
""".split())
_CASES = ("nomn", "gent", "datv", "accs", "ablt", "loct")


@register("punct-comma-deeprichastie", needs_morph=True)
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
            left = _strip_markup(sent.text[:m.start()])
            if not left or left[-1] in ",(«—–-:;":
                continue
            yield Hit(lineno=sent.lineno, col=sent.col + m.start(), matched=word,
                      detail="деепричастный оборот выделяется запятой")


@register("punct-comma-prichastie", needs_morph=True)
def comma_prichastie(doc, morph, entry: dict) -> Iterable[Hit]:
    """Постпозитивный причастный оборот without a comma: «изображения полученные …».

    Requires the participle to follow a noun it agrees with in case and number, and to head
    a phrase of its own (≥2 more words before the clause boundary). Multi-letter prepositions
    («по данным», «к имеющимся») never form the pair — `has_pos` takes only the top
    *dictionary* parse, under which «данным» is a noun and «по» is not. One- and two-letter
    tokens do: «в», «и», «Из» all top-parse as NOUN (letter names, abbreviations), so
    «Из включённых очагов» looked like a noun + participle. Length and the preposition list
    drop them.
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
            if len(prev) <= 2 or prev.lower() in _PREPOSITION:
                continue
            if not morph.has_pos(word, "PRTF") or not morph.has_pos(prev, "NOUN"):
                continue
            if _CLAUSE_BREAK.search(sent.text[prev_pos + len(prev):pos]):
                continue  # «…химиотерапия; планируемая резекция…» — «;» separates the
                #           enumeration items just as a comma would
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

    The anchor is regex, so the rule still works without morphology — but all three
    suppressors below (gerund, predicate, enumeration) are morphology-only, and precision
    drops once they go silent. Hence `severity_without_morph: "info"` on the entry rather
    than `needs_morph=True`, which would drop the rule entirely.
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
        if head and (head[-1].isspace() or "  " in head):
            continue  # the head crossed inline code, which `_strip_inline` left as a blank:
            #           «При ней `{python} …`, не …», «Для каждого метода на `{python} …`
            #           рассчитывали чувствительность, специфичность». Word count and
            #           adjacency mean nothing there, and real prose has neither a comma
            #           after a blank nor a double space
        head_words = _WORD.findall(head)
        if not head_words or len(head_words) > 6 or any(c in head for c in ".;:—–("):
            continue
        if morph.available and any(morph.has_pos(w, "GRND") for w in head_words):
            continue  # «Учитывая объём резекции, …» — the оборот earns its comma
        if morph.available and any(morph.has_pos(w, "VERB") or morph.has_pos(w, "PRTS")
                                   for w in head_words):
            continue  # a predicate before the comma means the clause already started:
            #           «Для каждого метода … рассчитывали чувствительность, специфичность».
            #           PRTS too — «При замене были бы потеряны метастазы, выявленные…»:
            #           «были» has a NOUN top parse («быль»), so only «потеряны» sees it
        after = rest[comma + 1:].lstrip()
        after_words = _WORD.findall(after)
        if not after or not after[0].islower() or not after_words:
            continue
        if after_words[0].lower() in _COORD:
            continue  # «…, но метки сравнивали» — the comma joins clauses
        if after_words[0].lower() in _SUBORD:
            continue  # «При планировании резекции, когда пропуск нежелателен, …» — the
            #           comma opens a subordinate clause and is required
        if _enumeration(morph, head_words[-1], after_words[0]):
            continue  # «Для чувствительности, специфичности, …» — an enumeration
        yield Hit(lineno=sent.lineno, col=sent.col + m.end() + comma,
                  matched=f"{m.group(1)} {head.strip()},",
                  detail="обстоятельство в начале предложения запятой не отделяется")


_KOTORYJ = re.compile(r"\bкотор(?:ый|ая|ое|ые|ого|ой|ых|ым|ыми|ому|ую|ом)\b", re.IGNORECASE)
_PREPOSITION = frozenset("""
в во на с со для из к ко по о об обо при у за от над под перед через между среди
до без про около после вокруг вместо кроме сквозь ради благодаря согласно
""".split())


@register("punct-comma-kotoryj")
def comma_kotoryj(doc, morph, entry: dict) -> Iterable[Hit]:
    """Missing comma before a «который» clause.

    As a pattern this could not tell «фазу, в которую» from «метастаз который»: any letter
    followed by a space satisfied the anchor, so the preposition matched itself and five of
    eight hits on the calibration corpus already had their comma. Walking back over an
    optional preposition and looking at the real previous character is exact.
    """
    for sent in doc.sentences:
        for m in _KOTORYJ.finditer(sent.text):
            head = sent.text[:m.start()].rstrip()
            if not head or head[-1] in ",(«—–-:;":
                continue
            if _comma_before_prepositional_group(head):
                continue  # «…, в каждый из которых…» — the comma sits before the group
            if _possessive(morph, head, m.group(0)):
                continue  # «Очаги, размеры которых превышали…» — genitive, no comma here
            yield Hit(lineno=sent.lineno, col=sent.col + m.start(), matched=m.group(0),
                      detail="придаточное с «который» отделяется запятой")


def _comma_before_prepositional_group(head: str) -> bool:
    """True when a preposition governs the clause and a comma already precedes that group.

    The group may be several words long («в каждый из которых»), so scan back a short
    window for the outermost preposition rather than just the adjacent token.
    """
    spans = [(m.group(0), m.start()) for m in _WORD.finditer(head)]
    for word, start in reversed(spans[-4:]):
        if word.lower() not in _PREPOSITION:
            continue
        before = head[:start].rstrip()  # index-based: `rsplit` matched the token mid-word
        if not before or before[-1] in ",(«—–-:;":
            return True
    return False


def _possessive(morph, head: str, pronoun: str) -> bool:
    """«…, размеры которых превышали…» — a genitive «который» after a noun is possessive
    ("whose"): it belongs to that noun phrase and takes no comma of its own.

    Case must **disagree** for that reading. «размеры»(nomn) vs «которых»(gent) is
    possessive; «пациента»(accs) vs «которого»(accs) is an ordinary relative clause that
    does need the comma — keying on the genitive tag alone silenced it.
    """
    if not morph.available or "gent" not in morph.top_tag(pronoun):
        return False
    words = _WORD.findall(head)
    if not words or not morph.has_pos(words[-1], "NOUN"):
        return False
    noun_tag = morph.top_tag(words[-1])
    return not any(c in noun_tag for c in ("gent",))


_COMPOUND_CONJ = re.compile(
    r"\bв\s+случае\s+если\b|\bв\s+то\s+время\s+как\b|\bнесмотря\s+на\s+то\s+что\b"
    r"|\bпо\s+мере\s+того\s+как\b|\bв\s+связи\s+с\s+тем\s+что\b"
    r"|\bв\s+зависимости\s+от\s+того\s+как\b|\bдля\s+того\s+чтобы\b", re.IGNORECASE)


@register("punct-comma-slozhnyj-soyuz")
def comma_compound_conjunction(doc, morph, entry: dict) -> Iterable[Hit]:
    """Compound conjunction that needs its internal comma: «в случае, если».

    Two placements are correct, so this is advisory (`warn`), not a gate: the comma may go
    before the whole conjunction («Резекцию отложили, несмотря на то что риск был низким»)
    or inside it, and which reads better depends on emphasis — Rosenthal §108. Only the
    third case, no comma anywhere, is reported:

    - fronted clause → the conjunction is never split, so skip;
    - a comma already precedes → already punctuated, skip.
    """
    for sent in doc.sentences:
        for m in _COMPOUND_CONJ.finditer(sent.text):
            head = _strip_markup(sent.text[:m.start()])
            if not head:
                continue  # fronted clause — the conjunction is not split
            if head[-1] in ",(«—–-:;":
                continue  # «…, в то время как …» — the comma is placed before the group
            yield Hit(lineno=sent.lineno, col=sent.col + m.start(), matched=m.group(0),
                      detail="нужна запятая: «в случае, если» или перед всем союзом")


_MARKUP_PREFIX = re.compile(r"^[\s>#*_`~+.)\d-]*")


def _strip_markup(head: str) -> str:
    """Drop list bullets, heading marks and emphasis so "is this the start of the sentence?"
    is not answered by column 1 alone — «- В то время как …» is still a fronted clause."""
    return _MARKUP_PREFIX.sub("", head).strip()


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
