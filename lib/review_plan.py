"""Single source of the review plan: the prose-reviewer dimensions and their launch
conditions live in `canon/review-dimensions.json`; `plan()` resolves them against the
document (mode, sections, before/after, claim registry) and every consumer dispatches
one reviewer per plan entry instead of a hand-maintained list."""
from __future__ import annotations
import argparse, json, re, sys
from dataclasses import asdict, dataclass
from pathlib import Path

from lib.claim_registry import check_document
from lib.checks.genre import _discussion_span
from lib.document import Document
from lib.lint_prose import ConfigError, changed_lines

_REGISTRY = Path(__file__).resolve().parents[1] / "canon" / "review-dimensions.json"
_MODES = ("diff", "light", "deep", "full")
_WHEN = {"always", "has_section:Обсуждение", "substantive_edit",
         "has_before_after", "claims_registry_valid"}
_FIELDS = ("id", "tier", "when", "skills", "source")
# Sections whose edits count as substantive («argument»); «Обсуждение» has its own
# dimensions and never counts here.
_SUBSTANTIVE = re.compile(
    r"\b(?:реферат\w*|аннотаци\w*|введени\w*|метод\w*|материал\w*|результат\w*"
    r"|заключени\w*|вывод\w*)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PlanEntry:
    id: str
    when: str
    reason: str


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
        if e["tier"] != "default":
            raise ConfigError(f"{p}: «{eid}» — tier должен быть «default»")
        if e["when"] not in _WHEN:
            raise ConfigError(f"{p}: «{eid}» — недопустимый when «{e['when']}»: "
                              f"ожидается {', '.join(sorted(_WHEN))}")
        skills = e["skills"]
        if not isinstance(skills, list) or not all(isinstance(s, str) for s in skills):
            raise ConfigError(f"{p}: «{eid}» — «skills» должно быть списком строк")
        if not isinstance(e["source"], str):
            raise ConfigError(f"{p}: «{eid}» — «source» должно быть строкой")
    return data


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


def plan(doc: Path, *, mode: str, spec: str | None = None, genre: str | None = None,
         before: Path | None = None) -> ReviewPlan:
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
            entries.append(PlanEntry(id=e["id"], when=when, reason=reason))
    return ReviewPlan(mode=mode, dimensions=tuple(entries))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Review plan: prose-reviewer dimensions to dispatch for a .qmd")
    ap.add_argument("doc")
    ap.add_argument("--mode", choices=list(_MODES), default="diff")
    ap.add_argument("--before", default=None,
                    help="pre-edit source (adds the fidelity dimension)")
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
        result = plan(doc, mode=args.mode, before=before)
    except ConfigError as e:
        print(f"review_plan: битый canon/review-dimensions.json — {e}", file=sys.stderr)
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
