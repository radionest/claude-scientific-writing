"""Single source of the review plan: the prose-reviewer dimensions and their launch
conditions live in `canon/review-dimensions.json`; `plan()` resolves them against the
document (mode, sections, before/after, claim registry) and every consumer dispatches
one reviewer per plan entry instead of a hand-maintained list."""
from __future__ import annotations
import argparse, json, re, sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from lib.claim_registry import check_document
from lib.checks.genre import _discussion_span
from lib.document import Document
from lib.house import load_house
from lib.lint_prose import ConfigError, changed_lines, effective_entries, lint_source
from lib.morph import Morph

_REGISTRY = Path(__file__).resolve().parents[1] / "canon" / "review-dimensions.json"
_ROOT = _REGISTRY.parents[1]
_MODES = ("diff", "light", "deep", "full")
_WHEN = {"always", "has_section:Обсуждение", "substantive_edit",
         "has_before_after", "claims_registry_valid"}
_FIELDS = ("id", "tier", "when", "skills", "source")
TIERS = ("fast", "strong")
# Sections whose edits count as substantive («argument»); «Обсуждение» has its own
# dimensions and never counts here.
_SUBSTANTIVE = re.compile(
    r"\b(?:реферат\w*|аннотаци\w*|введени\w*|метод\w*|материал\w*|результат\w*"
    r"|заключени\w*|вывод\w*)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PlanEntry:
    id: str
    tier: str  # fast | strong: the lane the dimension is dispatched on
    when: str
    reason: str
    covered_by_lint: bool = False  # terminology only: the pack's terms are linter-covered


@dataclass(frozen=True, slots=True)
class ReviewPlan:
    mode: str
    dimensions: tuple[PlanEntry, ...]


def load_registry(path: Path | None = None) -> list[dict]:
    """Validated entries of `canon/review-dimensions.json`; ConfigError (CLI exit 3)
    on a malformed file — the same contract the linter dictionaries carry."""
    p = path or _REGISTRY
    try:
        data = json.loads(p.read_text(encoding="utf-8"))["entries"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ConfigError(f"{p}: {e}") from e
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        raise ConfigError(f"{p}: ожидается «entries» — список объектов")
    seen: set[str] = set()
    for e in data:
        eid = e.get("id")
        if not isinstance(eid, str) or not eid:
            raise ConfigError(f"{p}: запись без строкового «id»")
        if eid in seen:
            raise ConfigError(f"{p}: повтор id «{eid}»")
        seen.add(eid)
        missing = [k for k in _FIELDS if k not in e]
        if missing:
            raise ConfigError(f"{p}: запись «{eid}» без полей: {', '.join(missing)}")
        if e["tier"] not in TIERS:
            raise ConfigError(f"{p}: «{eid}» — tier должен быть «fast» или «strong»")
        if e["when"] not in _WHEN:
            raise ConfigError(f"{p}: «{eid}» — недопустимый when «{e['when']}»: "
                              f"ожидается {', '.join(sorted(_WHEN))}")
        skills = e["skills"]
        if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
            raise ConfigError(f"{p}: «{eid}» — «skills» должно быть списком строк")
        if not isinstance(e["source"], str):
            raise ConfigError(f"{p}: «{eid}» — «source» должно быть строкой")
    return data


def effective_tiers(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Registry `tier` per dimension with the pack's `lanes` applied on top (override by
    dimension id). An id outside the registry or a value outside `TIERS` is ConfigError —
    a silent `fast` would route judgment dimensions to the weak lane."""
    tiers = {e["id"]: e["tier"] for e in load_registry()}
    if not overrides:
        return tiers
    outside = sorted(set(overrides) - tiers.keys())
    if outside:
        raise ConfigError(f"«lanes» в house.json — измерения вне реестра: {', '.join(outside)}")
    wrong = sorted(k for k, v in overrides.items() if v not in TIERS)
    if wrong:
        raise ConfigError(f"«lanes» в house.json — недопустимая полоса у {', '.join(wrong)}: "
                          f"ожидается {', '.join(TIERS)}")
    return {**tiers, **overrides}


def dimension_contracts(root: Path | None = None) -> dict[str, str]:
    """The dimension contract bullets keyed by id, extracted from the anchored agent
    files (`source` is `agents/<file>.md#<id>`): the text a dispatched reviewer is
    handed as its goal."""
    root = Path(root) if root is not None else _ROOT
    out: dict[str, str] = {}
    for e in load_registry():
        rel, anchor = e["source"].split("#", 1)
        text = (root / rel).read_text(encoding="utf-8")
        m = re.search(rf"(?ms)^- \*\*{re.escape(anchor)}\*\* — .*?(?=^- |^## |\Z)", text)
        if m is None:
            raise ConfigError(f"{rel}: контракт измерения «{anchor}» не найден")
        out[e["id"]] = m.group(0).rstrip()
    return out


def _substantive_lines(document: Document) -> set[int]:
    in_section = False
    level = 0
    out: set[int] = set()
    for pl in document.lines:
        h = pl.heading
        if h:
            if _SUBSTANTIVE.search(h[1]):
                if not in_section:
                    # the entry level is fixed once — a nested substantive heading keeps it,
                    # so its non-substantive siblings stay inside (see `_discussion_span`)
                    in_section, level = True, h[0]
            elif h[0] <= level:
                in_section = False
        if in_section:
            out.add(pl.lineno)
    return out


def _claims_registry_valid(doc: Path) -> bool:
    claims = doc.with_suffix(".claims.jsonl")
    if not claims.is_file():
        return False
    return not any(f.category == "schema" for f in check_document(doc, claims, None))


def _terminology_covered(doc: Path, source: str, *, dictionary: str | None,
                         local_dictionary: str | None, use_local: bool) -> bool:
    """The pack's `terms` plus a clean `doc-term-canon` run mean the linter already
    enforces the term canon on this document — the ensemble reviewer would re-check the
    same rule set the gate applies. Morphology-free rule, so the degraded run is exact."""
    entries, checks = effective_entries(doc, dictionary, local_dictionary, use_local)
    if not any(e["id"] == "doc-term-canon" and e.get("terms") for e in checks):
        return False
    findings = lint_source(source, entries, checks, Morph(available=False), file=str(doc))
    return not any(f.id == "doc-term-canon" for f in findings)


def plan(doc: Path, *, mode: str, spec: str | None = None, genre: str | None = None,
         before: Path | None = None, dictionary: str | None = None,
         local_dictionary: str | None = None, use_local: bool = True) -> ReviewPlan:
    if mode not in _MODES:
        raise ValueError(f"недопустимый mode «{mode}»: ожидается {', '.join(_MODES)}")
    source = doc.read_text(encoding="utf-8")
    document = Document.from_source(source)
    has_discussion = _discussion_span(document) is not None
    substantive_changed = 0
    if mode == "diff":
        substantive_changed = len(changed_lines(str(doc), None)
                                  & _substantive_lines(document))
    claims_name = doc.with_suffix(".claims.jsonl").name
    terminology_covered = _terminology_covered(doc, source, dictionary=dictionary,
                                               local_dictionary=local_dictionary,
                                               use_local=use_local)
    house = load_house(doc)
    tiers = effective_tiers(house.lanes if house else None)
    entries: list[PlanEntry] = []
    for e in load_registry():
        when = e["when"]
        if when == "always":
            included, reason = True, "входит в план всегда"
        elif when.startswith("has_section:"):
            included = has_discussion
            reason = f"в документе есть раздел «{when.split(':', 1)[1]}»"
        elif when == "substantive_edit":
            if mode in ("deep", "full"):
                included, reason = True, f"режим {mode}: содержательные секции ревьюятся целиком"
            else:
                included = mode == "diff" and substantive_changed >= 2
                reason = f"в diff изменены строки содержательного раздела ({substantive_changed})"
        elif when == "has_before_after":
            included = before is not None
            reason = f"передан --before ({before})" if before else ""
        else:
            included = _claims_registry_valid(doc)
            reason = f"валидный реестр {claims_name}" if included else ""
        if included:
            entries.append(PlanEntry(id=e["id"], tier=tiers[e["id"]], when=when, reason=reason,
                                     covered_by_lint=e["id"] == "terminology"
                                     and terminology_covered))
    return ReviewPlan(mode=mode, dimensions=tuple(entries))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Review plan: prose-reviewer dimensions to dispatch for a .qmd")
    ap.add_argument("doc")
    ap.add_argument("--mode", choices=list(_MODES), default="diff")
    ap.add_argument("--before", default=None,
                    help="pre-edit source (adds the fidelity dimension)")
    ap.add_argument("--dictionary", default=None)
    ap.add_argument("--local-dictionary", default=None,
                    help="use this file as the project-local dictionary (overrides auto-discovery)")
    ap.add_argument("--no-local", action="store_true",
                    help="ignore any project-local dictionary (overrides --local-dictionary)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = Path(args.doc)
    if not doc.is_file():
        print(f"file not found: {doc}", file=sys.stderr)
        return 2
    before = Path(args.before) if args.before else None
    if before is not None and not before.is_file():
        print(f"file not found: {before}", file=sys.stderr)
        return 2
    try:
        result = plan(doc, mode=args.mode, before=before, dictionary=args.dictionary,
                      local_dictionary=args.local_dictionary, use_local=not args.no_local)
    except ConfigError as e:
        print(f"review_plan: ошибка конфигурации — {e}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps({"mode": result.mode,
                          "dimensions": [asdict(d) for d in result.dimensions]},
                         ensure_ascii=False, indent=2))
    else:
        for d in result.dimensions:
            print(f"{d.id:11} {d.when:24} {d.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
