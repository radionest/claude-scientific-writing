"""Optional Russian morphology. Soft import — the linter runs without it, degraded.

`mawo-pymorphy3` quirks this adapter hides:
- it needs `dawg-python`; without it the analyzer silently falls back to a guesser-only mode;
- `MorphAnalyzer` has no `word_is_known()` — the dictionary lives on `_dawg_dict`;
- `Parse.is_known` is always True (the guesser fires), so `score == 1.0` is the
  known-word signal, not `is_known`.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class Morph:
    """Word-level morphology. `available is False` → every query answers "don't know"."""

    available: bool

    @staticmethod
    def load() -> "Morph":
        return Morph(available=_analyzer() is not None)

    def known(self, word: str) -> bool:
        """True only if `word` is in the dictionary. Unavailable morphology → False.

        The DAWG is ё-strict («включенных» misses, «включённых» hits), so a dictionary
        miss falls back to the parser, which normalises ё and still scores 1.0 only for
        real words.
        """
        if not self.available:
            return False
        w = word.lower()
        return _known(w) or _top_score(w) >= 1.0

    def top_tag(self, word: str) -> str:
        """Grammemes of the best parse, or "" when unavailable/unparsed."""
        return _top_tag(word.lower()) if self.available else ""

    def top_is_dictionary(self, word: str) -> bool:
        """True if the best parse comes from the dictionary rather than the guesser."""
        return _top_score(word.lower()) >= 1.0 if self.available else False

    def lemma(self, word: str) -> str:
        """Normal form, or the word itself when unavailable/unparsed."""
        return _lemma(word.lower()) if self.available else word.lower()

    def has_pos(self, word: str, pos: str) -> bool:
        """True if the best parse is `pos` (PRTF, GRND, NOUN, …) and comes from the dictionary.

        Guessed parses are rejected: bare POS tagging reads «время» as GRND and
        «нодулярная» as GRND, which is what makes naive participle/gerund comma
        rules unusable.
        """
        if not self.available:
            return False
        return _top_score(word.lower()) >= 1.0 and pos in _top_tag(word.lower())


@lru_cache(maxsize=1)
def _analyzer() -> object | None:
    try:
        import mawo_pymorphy3
    except ImportError:
        return None
    try:
        a = mawo_pymorphy3.MorphAnalyzer()
    except Exception:
        return None
    # Without dawg-python the fork degrades to a guesser with no dictionary: refuse it,
    # since every check here keys off dictionary membership.
    if getattr(a, "_dawg_dict", None) is None:
        return None
    return a


@lru_cache(maxsize=100_000)
def _known(word: str) -> bool:
    a = _analyzer()
    try:
        return bool(a._dawg_dict.word_is_known(word))  # type: ignore[union-attr]
    except Exception:
        return False


@lru_cache(maxsize=100_000)
def _best(word: str) -> object | None:
    a = _analyzer()
    try:
        parses = a.parse(word)  # type: ignore[union-attr]
    except Exception:
        return None
    return parses[0] if parses else None


def _top_tag(word: str) -> str:
    p = _best(word)
    return str(p.tag) if p is not None else ""


def _top_score(word: str) -> float:
    p = _best(word)
    return float(getattr(p, "score", 0.0)) if p is not None else 0.0


def _lemma(word: str) -> str:
    p = _best(word)
    return str(p.normal_form) if p is not None else word
