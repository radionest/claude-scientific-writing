"""Project pack: repo-wide writing data next to the overlay dictionary.

`<git-root>/.claude/scientific-writing/house.json` carries what every document of a
project shares: canonical terms (forbidden synonyms, admissible-with-caution variants),
abbreviations, the editorial passport, norms and house-style samples. Discovery mirrors
`lint_prose.local_dict_path` — a linked worktree's own copy wins over the main checkout's.
A malformed file, an unknown key or a wrong field type raise `ConfigError` (the CLIs map
it to exit 3).
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

from lib.lint_prose import ConfigError, _git_main_root, _git_root

_HOUSE_RELPATH = Path(".claude") / "scientific-writing" / "house.json"
_NORMS_PATH = Path(__file__).resolve().parents[1] / "canon" / "norms.json"
_FIELDS = frozenset({"name", "genre_default", "terms", "abbreviations", "passport",
                     "norms", "samples", "lanes"})
_TERM_FIELDS = frozenset({"canonical", "forbidden", "caution", "note"})
_ABBR_FIELDS = frozenset({"abbr", "expansion"})
_NORM_FIELDS = frozenset({"id", "text", "source"})
# JSON keys are the «Редакционного паспорта» rows; slots are the dataclass fields.
_PASSPORT_KEYS = {"numbers": "numbers", "dates": "dates", "ranges": "ranges",
                  "units": "units", "list-markers": "list_markers", "headings": "headings",
                  "links": "links", "house-style": "house_style"}


@dataclass(frozen=True, slots=True)
class Term:
    canonical: str
    forbidden: tuple[str, ...] = ()
    caution: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True, slots=True)
class Abbreviation:
    abbr: str
    expansion: str


@dataclass(frozen=True, slots=True)
class Norm:
    id: str
    text: str
    source: str = ""


@dataclass(frozen=True, slots=True)
class Passport:
    numbers: str = ""
    dates: str = ""
    ranges: str = ""
    units: str = ""
    list_markers: str = ""
    headings: str = ""
    links: str = ""
    house_style: str = ""


@dataclass(frozen=True, slots=True)
class House:
    name: str = ""
    genre_default: str = ""
    terms: tuple[Term, ...] = ()
    abbreviations: tuple[Abbreviation, ...] = ()
    passport: Passport = Passport()
    norms: tuple[Norm, ...] = ()
    samples: tuple[str, ...] = ()
    lanes: tuple[str, ...] = ()


def house_path(target: str | Path) -> Path | None:
    root = _git_root(Path(target).resolve().parent)
    if root is None:
        return None
    own = root / _HOUSE_RELPATH
    if own.exists():
        return own  # the worktree's own copy wins over the main checkout's
    main_root = _git_main_root(root)
    if main_root is not None and main_root != root:
        main = main_root / _HOUSE_RELPATH
        if main.exists():
            return main
    return None


def load_house(doc_path: str | Path) -> House | None:
    p = house_path(doc_path)
    if p is None:
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"{p}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{p}: ожидается объект с полями пакета")
    unknown = sorted(set(data) - _FIELDS)
    if unknown:
        raise ConfigError(f"{p}: неизвестные поля: {', '.join(unknown)}")
    house = House(
        name=_text(p, data, "name"),
        genre_default=_text(p, data, "genre_default"),
        terms=tuple(
            Term(canonical=x["canonical"].strip(),
                 forbidden=tuple(_strings(p, "terms.forbidden", x.get("forbidden"))),
                 caution=tuple(_strings(p, "terms.caution", x.get("caution"))),
                 note=_text(p, x, "note"))
            for x in _records(p, data, "terms", _TERM_FIELDS, ("canonical",))),
        abbreviations=tuple(
            Abbreviation(abbr=x["abbr"].strip(), expansion=x["expansion"])
            for x in _records(p, data, "abbreviations", _ABBR_FIELDS, ("abbr", "expansion"))),
        passport=_passport(p, data.get("passport")),
        norms=tuple(
            Norm(id=x["id"], text=x["text"], source=_text(p, x, "source"))
            for x in _records(p, data, "norms", _NORM_FIELDS, ("id", "text"))),
        samples=tuple(_strings(p, "samples", data.get("samples"))),
        lanes=tuple(_strings(p, "lanes", data.get("lanes"))),
    )
    ids = [n.id for n in house.norms]
    if len(ids) != len(set(ids)):
        raise ConfigError(f"{p}: повтор id в «norms»")
    return house


def load_norms(house: House | None = None) -> list[Norm]:
    """`canon/norms.json` ⊕ the pack's `norms` (override by id): the project rewords or
    extends a default, and the `norms:<id>` references in `canon/profiles/*.md` and the
    skills stay stable."""
    try:
        data = json.loads(_NORMS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"{_NORMS_PATH}: {e}") from e
    if not isinstance(data, list):
        raise ConfigError(f"{_NORMS_PATH}: ожидается список норм")
    by_id: dict[str, Norm] = {}
    for x in data:
        n = _norm(_NORMS_PATH, x)
        if n.id in by_id:
            raise ConfigError(f"{_NORMS_PATH}: повтор id «{n.id}»")
        by_id[n.id] = n
    for n in house.norms if house else ():
        by_id[n.id] = n
    return list(by_id.values())


def _norm(p: Path, x: object) -> Norm:
    if not isinstance(x, dict) or set(x) - _NORM_FIELDS \
            or not _is_text(x.get("id")) or not _is_text(x.get("text")):
        raise ConfigError(f"{p}: норма — объект {{id, text, source?}} с непустыми строками")
    source = x.get("source")
    if source is not None and not isinstance(source, str):
        raise ConfigError(f"{p}: «source» должно быть строкой")
    return Norm(id=x["id"], text=x["text"], source=source or "")


def _is_text(v: object) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _records(p: Path, data: dict, field: str, allowed: frozenset[str],
             need: tuple[str, ...]) -> list[dict]:
    v = data.get(field)
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        raise ConfigError(f"{p}: «{field}» должен быть списком объектов")
    for x in v:
        unknown = sorted(set(x) - allowed)
        if unknown:
            raise ConfigError(f"{p}: «{field}» — неизвестные поля записи: {', '.join(unknown)}")
        missing = [k for k in need if not _is_text(x.get(k))]
        if missing:
            raise ConfigError(
                f"{p}: «{field}» — запись без непустого строкового поля: {', '.join(missing)}")
    return v


def _strings(p: Path, where: str, v: object) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{p}: «{where}» должно быть списком непустых строк")
    stripped = [x.strip() for x in v]  # a padded phrase would silently break matching
    if not all(stripped):
        raise ConfigError(f"{p}: «{where}» должно быть списком непустых строк")
    return stripped


def _text(p: Path, obj: dict, key: str) -> str:
    v = obj.get(key)
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ConfigError(f"{p}: «{key}» должно быть строкой")
    return v


def _passport(p: Path, v: object) -> Passport:
    if v is None:
        return Passport()
    if not isinstance(v, dict):
        raise ConfigError(f"{p}: «passport» должен быть объектом")
    unknown = sorted(set(v) - set(_PASSPORT_KEYS))
    if unknown:
        raise ConfigError(f"{p}: «passport» — неизвестные поля: {', '.join(unknown)}")
    wrong = sorted(k for k, x in v.items() if not _is_text(x))
    if wrong:
        raise ConfigError(f"{p}: «passport» — не строковые значения: {', '.join(wrong)}")
    return Passport(**{_PASSPORT_KEYS[k]: x for k, x in v.items()})
