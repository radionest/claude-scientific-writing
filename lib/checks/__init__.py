"""Registry of code checks — rules a regex cannot express.

A dictionary entry stays `kind: "regex"`. An entry with `kind: "check"` names a function
here instead of a pattern, so severity, message, `except`, `allow` and `<!-- lint-ok -->`
suppression keep working the same way for both kinds.

    Check = Callable[[Document, Morph, dict], Iterable[Hit]]

A check yields `Hit`s; `lib.lint_prose` turns them into `Finding`s, stamping the entry's
id/severity/message. A check that needs morphology it does not have should yield nothing.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from lib.document import Document
    from lib.morph import Morph


@dataclass(frozen=True, slots=True)
class Hit:
    lineno: int
    col: int  # 1-based
    matched: str
    detail: str = ""  # appended to the entry message when present


Check = Callable[["Document", "Morph", dict], Iterable[Hit]]

_REGISTRY: dict[str, Check] = {}


def register(rule_id: str) -> Callable[[Check], Check]:
    def deco(fn: Check) -> Check:
        _REGISTRY[rule_id] = fn
        return fn
    return deco


def get(rule_id: str) -> Check | None:
    _load_all()
    return _REGISTRY.get(rule_id)


def known_ids() -> frozenset[str]:
    _load_all()
    return frozenset(_REGISTRY)


_loaded = False


def _load_all() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from lib.checks import consistency, hyphenation, punctuation, spelling  # noqa: F401
