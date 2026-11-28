"""Owner-style profile: robust style features of one text vs a pack-sample baseline.

`profile` turns a document (raw .qmd or plain prose) into a fixed vector of style
features; `baseline` aggregates approved samples — the pack's `house.samples` or a
calibration corpus — into per-feature (median, MAD); `distance` scores a profile
against such a baseline as robust z-scores. The `/eval-prose --only style` contour
runs these over machine/human corpora; a feature becomes a calibrated marker only
when its machine-vs-human direction agrees in at least two corpora. The feature set
deliberately keys off none of the sanctioned constructs (тире, «является», «данный»).
"""
from __future__ import annotations
import math
import re
from collections.abc import Mapping, Sequence
from statistics import fmean, median

from lib.document import Document
from lib.morph import Morph
from lib.qmd_prose import extract_prose

FEATURES: tuple[str, ...] = (
    "wps", "long_sent_share", "commas_per_sent", "parens_per_sent", "mattr",
    "nom_density", "connectives_per_sent", "first_person_1k", "rare_ratio",
)

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_LONG_SENT = 40  # words — the «предложение-обоз» boundary the prose skill diagnoses
_MATTR_WINDOW = 100  # tokens; below that a plain TTR over the whole text
_MAX_WORDS = 5000  # deterministic head-cap for the expensive word-level features
_NOM_SUFFIXES = (
    "ение", "ения", "ению", "ением", "ений", "яние", "яния", "анию", "анием",
    "аний", "ация", "ации", "ацию", "ацией", "аций", "ациями", "ость", "ости",
    "остью", "остей", "ство", "ства", "ству", "ством",
)
_CONNECTIVE = re.compile(
    r"\b(?:однако|таким образом|при этом|кроме того|в то же время|следовательно"
    r"|более того|в частности|поэтому|соответственно)\b", re.IGNORECASE)
_FIRST_PERSON = frozenset({
    "мы", "нами", "нам", "нас", "наш", "наша", "наше", "наши", "нашего",
    "нашему", "нашим", "наших", "нашими",
})


def profile(doc: str, morph: Morph) -> dict[str, float]:
    """Style features over the narrative prose of `doc`; a text with no prose
    sentences or no words profiles to all zeros (a baseline of empty fragments
    must stay comparable, not crash)."""
    sents = Document.from_source(doc).sentences
    words = [m.group(0).lower() for pl in extract_prose(doc)
             for m in _WORD.finditer(pl.text)][:_MAX_WORDS]
    if not sents or not words:
        return dict.fromkeys(FEATURES, 0.0)
    return {
        "wps": fmean(len(_WORD.findall(s.text)) for s in sents),
        "long_sent_share": fmean(
            len(_WORD.findall(s.text)) >= _LONG_SENT for s in sents),
        "commas_per_sent": fmean(s.text.count(",") for s in sents),
        "parens_per_sent": fmean(s.text.count("(") for s in sents),
        "mattr": _mattr(words),
        "nom_density": fmean(w.endswith(_NOM_SUFFIXES) for w in words),
        "connectives_per_sent": fmean(len(_CONNECTIVE.findall(s.text)) for s in sents),
        "first_person_1k": 1000.0 * fmean(w in _FIRST_PERSON for w in words),
        "rare_ratio": _rare_ratio(words, morph),
    }


def baseline(samples: Sequence[str], morph: Morph) -> dict[str, tuple[float, float]]:
    """Per-feature (median, MAD) over the samples — what `distance` scores against."""
    cols = [profile(s, morph) for s in samples]
    if not cols:
        return {k: (0.0, 0.0) for k in FEATURES}
    out: dict[str, tuple[float, float]] = {}
    for k in FEATURES:
        col = [c[k] for c in cols]
        med = median(col)
        out[k] = (med, median([abs(x - med) for x in col]))
    return out


def distance(prof: Mapping[str, float],
             base: Mapping[str, tuple[float, float]]) -> dict[str, float]:
    """Robust z-scores: (value − median) / (1.4826·MAD). A degenerate MAD (samples
    all equal on the feature) yields 0.0 at the baseline value itself, ±inf off it —
    an infinite distance is the signal, not an error."""
    out: dict[str, float] = {}
    for k in FEATURES:
        med, mad = base.get(k, (0.0, 0.0))
        spread = 1.4826 * mad
        delta = prof.get(k, 0.0) - med
        if spread > 0:
            out[k] = delta / spread
        else:
            out[k] = 0.0 if delta == 0 else math.copysign(math.inf, delta)
    return out


def _mattr(words: list[str]) -> float:
    if len(words) <= _MATTR_WINDOW:
        return len(set(words)) / len(words)
    return fmean(len(set(words[i:i + _MATTR_WINDOW])) / _MATTR_WINDOW
                 for i in range(len(words) - _MATTR_WINDOW + 1))


def _rare_ratio(words: list[str], morph: Morph) -> float:
    if not morph.available:
        return 0.0
    return 1.0 - fmean(morph.known(w) for w in words)
