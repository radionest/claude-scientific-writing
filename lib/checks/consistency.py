"""Whole-document consistency: abbreviations, token casing, near repeats.

None of these can be decided from one line, which is why they need `Document` rather than
a dictionary pattern.
"""
from __future__ import annotations
import re
from collections import Counter, defaultdict
from typing import Iterable

from lib.checks import Hit, register

# КТ, КТ-АГ, ио-УЗИ, м-КРР — an uppercase core, optionally hyphenated to a short affix.
_ABBR = re.compile(r"(?<![\w-])(?:[А-ЯЁ]{2,}(?:-[А-ЯЁа-яё]{1,5})?|[а-яё]{1,2}-[А-ЯЁ]{2,})(?![\w-])")
# Alphanumeric run with both a digit and a letter: 3d/3D, icg/ICG, R1vasc. Hyphens are
# boundaries, so «3D-модель» contributes «3D» and compares against a bare «3d».
_MIXED_TOKEN = re.compile(r"(?<!\w)(?=\w*\d)(?=\w*[A-Za-zА-Яа-яЁё])\w{2,}(?!\w)")
_WORD = re.compile(r"[^\W\d_]{5,}", re.UNICODE)
# Words whose repetition is terminological, not clumsy.
_STOP_REPEAT = frozenset("""
очаг очаги метастаз метастазы печень пациент пациенты исследование метод методы
резекция контрастирование чувствительность специфичность модель
""".split())


@register("doc-abbrev-variants")
def abbrev_variants(doc, morph, entry: dict) -> Iterable[Hit]:
    """The same abbreviation spelled two ways: ИОУЗИ vs ио-УЗИ."""
    allow = {w.upper() for w in entry.get("allow", ())}
    by_key: dict[str, dict[str, list[tuple[int, int]]]] = defaultdict(lambda: defaultdict(list))
    for pl in doc.lines:
        for m in _ABBR.finditer(pl.text):
            tok = m.group(0)
            if tok.upper() in allow:
                continue
            by_key[tok.upper().replace("-", "")][tok].append((pl.lineno, m.start() + 1))
    for key, variants in sorted(by_key.items()):
        if len(variants) < 2:
            continue
        names = ", ".join(f"«{v}»" for v in sorted(variants))
        rarest = min(variants, key=lambda v: len(variants[v]))
        lineno, col = variants[rarest][0]
        yield Hit(lineno=lineno, col=col, matched=rarest,
                  detail=f"одна аббревиатура записана по-разному: {names}")


@register("doc-abbrev-first-use")
def abbrev_first_use(doc, morph, entry: dict) -> Iterable[Hit]:
    """An abbreviation expanded — «… (ИОУЗИ)» — later than its first bare use."""
    allow = {w.upper() for w in entry.get("allow", ())}
    first: dict[str, tuple[int, int]] = {}
    defined: dict[str, tuple[int, int]] = {}
    for pl in doc.lines:
        for m in _ABBR.finditer(pl.text):
            tok = m.group(0).upper()
            if tok in allow:
                continue
            first.setdefault(tok, (pl.lineno, m.start() + 1))
            before = pl.text[:m.start()].rstrip()
            if before.endswith("(") and tok not in defined:
                defined[tok] = (pl.lineno, m.start() + 1)
    for tok, (dline, dcol) in sorted(defined.items()):
        fline, fcol = first[tok]
        if (dline, dcol) > (fline, fcol):
            yield Hit(lineno=dline, col=dcol, matched=tok,
                      detail=f"раскрытие после первого употребления (строка {fline})")


@register("doc-token-case")
def token_case(doc, morph, entry: dict) -> Iterable[Hit]:
    """The same alphanumeric token in two casings: «3d» and «3D», «icg» and «ICG».

    Reports **every** occurrence of each non-dominant spelling, not just the first: in
    `--diff` mode (the hook path) a finding anchored on an untouched line is filtered out,
    so a newly introduced «3d» would otherwise slip through silently.

    The dominant spelling is simply the most frequent one. On a tie there is no evidence for
    a norm, so every spelling is reported and the message names none of them canonical —
    picking one anyway pointed at the correct «3D» and called the typo «3d» the standard.
    """
    allow = {w.lower() for w in entry.get("allow", ())}
    counts: dict[str, Counter] = defaultdict(Counter)
    spots: dict[str, dict[str, list[tuple[int, int]]]] = defaultdict(lambda: defaultdict(list))
    order: dict[str, dict[str, int]] = defaultdict(dict)
    seq = 0
    for pl in doc.lines:
        for m in _MIXED_TOKEN.finditer(pl.text):
            tok = m.group(0)
            if tok.lower() in allow:
                continue
            counts[tok.lower()][tok] += 1
            spots[tok.lower()][tok].append((pl.lineno, m.start() + 1))
            order[tok.lower()].setdefault(tok, seq)
            seq += 1
    for key, variants in sorted(counts.items()):
        if len(variants) < 2:
            continue
        top = max(variants.values())
        leaders = [v for v in variants if variants[v] == top]
        dominant = leaders[0] if len(leaders) == 1 else None
        tally = ", ".join(f"«{v}» ×{variants[v]}"
                          for v in sorted(variants, key=lambda v: (-variants[v], order[key][v])))
        for variant in sorted(variants, key=lambda v: order[key][v]):
            if variant == dominant:
                continue
            detail = (f"регистр непоследователен: {tally} — приведи к «{dominant}»"
                      if dominant else f"регистр непоследователен: {tally} — выбери одно написание")
            for lineno, col in spots[key][variant]:
                yield Hit(lineno=lineno, col=col, matched=variant, detail=detail)


_REPEAT_WINDOW = 12  # tokens; wider than this reads as normal scientific prose


@register("doc-repeat-window")
def repeat_window(doc, morph, entry: dict) -> Iterable[Hit]:
    """The same lemma twice within a few words — «с использованием … с использованием».

    Terminology is *supposed* to repeat, so a lemma the document uses often is treated as
    a term and exempted. That threshold is derived from the document itself, which beats
    any fixed stop-list: «очаг» and «контрастирование» disqualify themselves.
    """
    allow = {w.lower() for w in entry.get("allow", ())} | _STOP_REPEAT
    freq = _lemma_freq(doc, morph)
    limit = max(4, entry.get("term_frequency", 6))
    for sent in doc.sentences:
        toks = [(m.group(0), m.start()) for m in _WORD.finditer(sent.text)]
        last: dict[str, tuple[int, str]] = {}
        for i, (surface, pos) in enumerate(toks):
            word = surface.lower()
            if word in allow or (surface[0].isupper() and i > 0):
                continue  # proper nouns repeat legitimately (author lists, city names)
            key = _key(word, morph)
            if key in allow or freq.get(key, 0) > limit:
                continue
            prev = last.get(key)
            if prev is not None and i - prev[0] <= _REPEAT_WINDOW:
                yield Hit(lineno=sent.lineno, col=sent.col + pos, matched=surface,
                          detail=f"повтор рядом: «{prev[1]}» → «{surface}»")
                last.pop(key, None)
            else:
                last[key] = (i, surface)


def _key(word: str, morph) -> str:
    return morph.lemma(word) if morph.available else word[:6]


def _lemma_freq(doc, morph) -> dict[str, int]:
    freq: Counter = Counter()
    for pl in doc.lines:
        for m in _WORD.finditer(pl.text):
            freq[_key(m.group(0).lower(), morph)] += 1
    return freq
