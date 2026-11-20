"""Whole-document consistency: abbreviations, token casing, near repeats.

None of these can be decided from one line, which is why they need `Document` rather than
a dictionary pattern.
"""
from __future__ import annotations
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable

from lib.checks import Hit, register

# КТ, КТ-АГ, ио-УЗИ, м-КРР — an uppercase core, optionally hyphenated to a short affix.
_ABBR = re.compile(r"(?<![\w-])(?:[А-ЯЁ]{2,}(?:-[А-ЯЁа-яё]{1,5})?|[а-яё]{1,2}-[А-ЯЁ]{2,})(?![\w-])")
# Alphanumeric run with both a digit and a letter: 3d/3D, icg/ICG, R1vasc. Hyphens are
# boundaries, so «3D-модель» contributes «3D» and compares against a bare «3d».
_MIXED_TOKEN = re.compile(r"(?<!\w)(?=\w*\d)(?=\w*[A-Za-zА-Яа-яЁё])\w{2,}(?!\w)")
_WORD = re.compile(r"[^\W\d_]{5,}", re.UNICODE)
# The title block, abstract and keywords are their own abbreviation scope: a journal article
# re-expands abbreviations at their first use in the body. Everything before the first
# level-1 heading is that front matter.
_BODY_HEADING = re.compile(r"^\s*#\s+\S")
# A markdown list marker: leading indent, then a bullet (-, *, +) or an ordered number
# with a period or a closing paren. ^ anchors at the line start — `doc.lines` carries
# one line per ProseLine, so the marker is matched once per line.
_LIST_MARKER = re.compile(r"^( +)?([-*+]|\d{1,3}[.)])(?=\s)")


def _abbr_key(tok: str) -> str:
    """Canonical spelling for comparison: case-folded, hyphens dropped («ио-УЗИ» == «ИОУЗИ»)."""
    return tok.upper().replace("-", "")


def _variant_hits(doc, pattern: re.Pattern[str], key: Callable[[str], str],
                  allow: set[str], detail: Callable[[str | None, str], str],
                  dominant_detail: Callable[[str, str], str]) -> Iterable[Hit]:
    """Hits at **every** occurrence of each spelling of a token the document writes in
    several ways, the dominant one included.

    In `--diff` mode (the hook path) a finding anchored on an untouched line is filtered
    out, so a single anchor would let newly introduced deviations slip through. That is
    why the dominant spelling is anchored too: when an edit flips dominance, its own
    occurrences sit on the changed lines. The dominant spelling is the most frequent one;
    on a tie there is no evidence for a norm, so every spelling is reported and the
    message names none of them canonical.

    `key` folds a surface token to its canonical form, `allow` holds exempt keys,
    `detail(dominant, tally)` renders the message for a deviating occurrence and
    `dominant_detail(dominant, tally)` for the dominant spelling's own occurrences.
    """
    counts: dict[str, Counter] = defaultdict(Counter)
    spots: dict[str, dict[str, list[tuple[int, int]]]] = defaultdict(lambda: defaultdict(list))
    order: dict[str, dict[str, int]] = defaultdict(dict)
    seq = 0
    for pl in doc.lines:
        for m in pattern.finditer(pl.text):
            tok = m.group(0)
            k = key(tok)
            if k in allow:
                continue
            counts[k][tok] += 1
            spots[k][tok].append((pl.lineno, m.start() + 1))
            order[k].setdefault(tok, seq)
            seq += 1
    for k in sorted(counts):
        variants = counts[k]
        if len(variants) < 2:
            continue
        top = max(variants.values())
        leaders = [v for v in variants if variants[v] == top]
        dominant = leaders[0] if len(leaders) == 1 else None
        tally = ", ".join(f"«{v}» ×{variants[v]}"
                          for v in sorted(variants, key=lambda v: (-variants[v], order[k][v])))
        text = detail(dominant, tally)
        dominant_text = dominant_detail(dominant, tally) if dominant else None
        for variant in sorted(variants, key=lambda v: order[k][v]):
            for lineno, col in spots[k][variant]:
                yield Hit(lineno=lineno, col=col, matched=variant,
                          detail=dominant_text if variant == dominant else text)


@register("doc-abbrev-variants")
def abbrev_variants(doc, morph, entry: dict) -> Iterable[Hit]:
    """The same abbreviation spelled two ways: ИОУЗИ vs ио-УЗИ."""
    yield from _variant_hits(
        doc, _ABBR, key=_abbr_key,
        allow={_abbr_key(w) for w in entry.get("allow", ())},
        detail=lambda dominant, tally:
            f"{tally} — приведи к «{dominant}»" if dominant else f"{tally} — выбери одно написание",
        dominant_detail=lambda d, t: f"{t} — это написание преобладает, остальные приведи к нему")


@dataclass(frozen=True, slots=True)
class _Use:
    """One abbreviation occurrence: position and whether it is the «… (АББР)» expansion."""
    pos: tuple[int, int]
    expanded: bool


@register("doc-abbrev-first-use")
def abbrev_first_use(doc, morph, entry: dict) -> Iterable[Hit]:
    """An abbreviation expanded — «… (ИОУЗИ)» — later than its first bare use.

    Front matter and body are separate scopes, so «КТ» in the title and abstract does not
    make the Introduction's «компьютерная томография (КТ)» a late expansion.

    Every bare use made before the expansion is reported, plus the expansion itself, like
    `doc-token-case`: in `--diff` mode (the hook path) a finding on an untouched line is
    filtered out, and the newly added bare use is exactly the line that must not slip
    through.
    """
    allow = {w.upper() for w in entry.get("allow", ())}
    body = _body_start(doc)
    uses: dict[tuple[bool, str], list[_Use]] = defaultdict(list)
    for pl in doc.lines:
        for m in _ABBR.finditer(pl.text):
            tok = m.group(0).upper()
            if tok in allow:
                continue
            key = (pl.lineno >= body, tok)
            expanded = pl.text[:m.start()].rstrip().endswith("(")
            uses[key].append(_Use((pl.lineno, m.start() + 1), expanded))
    for key, spots in sorted(uses.items()):
        tok = key[1]
        defs = [u.pos for u in spots if u.expanded]
        if not defs:
            continue
        dpos = min(defs)
        bare = [u.pos for u in spots if not u.expanded and u.pos < dpos]
        if not bare:
            continue
        for lineno, col in bare:
            yield Hit(lineno=lineno, col=col, matched=tok,
                      detail=f"до раскрытия на строке {dpos[0]}")
        yield Hit(lineno=dpos[0], col=dpos[1], matched=tok,
                  detail=f"первое употребление на строке {bare[0][0]}")


def _body_start(doc) -> int:
    """Line of the first level-1 heading, or 0 when the document has none (a report or a
    fragment — then everything is one scope, as before)."""
    for pl in doc.lines:
        if _BODY_HEADING.match(pl.text):
            return pl.lineno
    return 0


@register("doc-token-case")
def token_case(doc, morph, entry: dict) -> Iterable[Hit]:
    """The same alphanumeric token in two casings: «3d» and «3D», «icg» and «ICG».

    On a tie there is no evidence for a norm, so every spelling is reported and the
    message names none of them canonical — picking one anyway pointed at the correct
    «3D» and called the typo «3d» the standard.
    """
    yield from _variant_hits(
        doc, _MIXED_TOKEN, key=str.lower,
        allow={w.lower() for w in entry.get("allow", ())},
        detail=lambda dominant, tally:
            f"регистр непоследователен: {tally} — приведи к «{dominant}»"
            if dominant else f"регистр непоследователен: {tally} — выбери одно написание",
        dominant_detail=lambda d, t:
            f"регистр непоследователен: {t} — «{d}» преобладает, остальные приведи к нему")


_REPEAT_WINDOW = 12  # tokens; wider than this reads as normal scientific prose


@register("doc-repeat-window")
def repeat_window(doc, morph, entry: dict) -> Iterable[Hit]:
    """The same lemma twice within a few words — «с использованием … с использованием».

    Terminology is *supposed* to repeat, so a lemma the document uses often is treated as
    a term and exempted. The threshold is derived from the document itself and does not
    see a short text, where a term stays under it — those terms come in through the
    entry's `allow` list in canon/orthography.json, which a project overlay replaces
    field-wise.
    """
    allow = {w.lower() for w in entry.get("allow", ())}
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


@register("doc-list-marker-consistency")
def list_marker_consistency(doc, morph, entry: dict) -> Iterable[Hit]:
    """One marker style per list nesting level: «-» vs «*» vs «+», «N.» vs «N)».

    Different levels legitimately differ — the educational genre nests its lists in
    its own style — and a bullet beside an ordered item is two lists, not a mix, so
    the key folds a marker to (indent width, family). Within a family the style, not
    the surface marker, is compared: "1.", "2.", "3." are one style (displayed
    «N.»), "1)" and "2)" are the other («N)»). Same anchoring as `_variant_hits`:
    in `--diff` mode (the hook path) a finding on an untouched line is filtered out,
    so every occurrence of the minority style and of the dominant one is reported.
    """
    counts: dict[str, Counter] = defaultdict(Counter)
    spots: dict[str, dict[str, list[tuple[int, int]]]] = defaultdict(lambda: defaultdict(list))
    for pl in doc.lines:
        m = _LIST_MARKER.match(pl.text)
        if m is None:
            continue
        indent, marker = m.group(1) or "", m.group(2)
        family = "ordered" if marker[0].isdigit() else "bullet"
        style = marker[-1] if family == "ordered" else marker
        display = f"N{style}" if family == "ordered" else style
        key = f"{len(indent)}|{family}"
        counts[key][display] += 1
        spots[key][display].append((pl.lineno, m.start(2) + 1))
    for key in sorted(counts):
        variants = counts[key]
        if len(variants) < 2:
            continue
        top = max(variants.values())
        leaders = [v for v in variants if variants[v] == top]
        dominant = leaders[0] if len(leaders) == 1 else None
        tally = ", ".join(f"«{v}» ×{variants[v]}" for v in variants)
        for style, occurrences in spots[key].items():
            if style == dominant:
                detail = f"{tally} — «{style}» преобладает, остальные приведи к нему"
            elif dominant is None:
                detail = f"{tally} — выбери один маркер на уровень"
            else:
                detail = f"{tally} — приведи к «{dominant}»"
            for lineno, col in occurrences:
                yield Hit(lineno=lineno, col=col, matched=style, detail=detail)
