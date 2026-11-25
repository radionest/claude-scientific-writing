"""Lane measurement: score reviewer findings against a human gold table.

A reviewer finding counts as a hit when its line falls inside the anchor range of a
gold finding of the same dimension; findings outside any anchor are the run's extra.
Alongside the per-run scores the report carries the share of gold findings that at
least one reviewer found. A dimension with fewer than three gold findings gets
`no_verdict`, and `fidelity` is not measured: its minimal pairs are meaning deltas,
not line-anchored findings of this document. The gold table is project-side data
(`<git-root>/.claude/scientific-writing/gold/<doc>.json`); the plugin keeps only the
path convention (docs/design.md) — a run file is the sw-review workflow's return shape
`{runs: [{dimension, tier, findings}]}` written by the caller, one file per reviewer.

    python -m lib.lane_measure --gold <table.json> --runs <dir> --out <report.json>
"""
from __future__ import annotations
import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lib.lint_prose import ConfigError

_NO_VERDICT_MIN = 3
_UNMEASURED = ("fidelity",)


@dataclass(frozen=True, slots=True)
class GoldItem:
    dimension: str
    line_start: int
    line_end: int


def load_gold(path: Path) -> list[GoldItem]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"{path}: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ConfigError(f"{path}: ожидается объект {{items: [...]}}")
    out: list[GoldItem] = []
    for i, x in enumerate(data["items"]):
        if (not isinstance(x, dict) or not isinstance(x.get("dimension"), str)
                or not isinstance(x.get("line_start"), int)
                or not isinstance(x.get("line_end"), int)):
            raise ConfigError(f"{path}: запись {i} — объект "
                              f"{{file, dimension, line_start, line_end}}")
        if x["line_start"] > x["line_end"]:
            raise ConfigError(f"{path}: запись {i} — line_start > line_end")
        out.append(GoldItem(dimension=x["dimension"],
                            line_start=x["line_start"], line_end=x["line_end"]))
    return out


def _load_runs(runs_dir: Path) -> list[tuple[str, list[dict]]]:
    """(run name, findings) per `*.json` in the runs directory — the run name is the
    file stem; the workflow's plan/route fields are metadata the scorer ignores."""
    out: list[tuple[str, list[dict]]] = []
    for p in sorted(runs_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ConfigError(f"{p}: {e}") from e
        runs = data.get("runs") if isinstance(data, dict) else None
        if not isinstance(runs, list):
            raise ConfigError(f"{p}: ожидается объект {{runs: [...]}} — "
                              f"возвращаемая форма workflow sw-review")
        findings = [f for r in runs if isinstance(r, dict)
                    for f in (r.get("findings") or []) if isinstance(f, dict)]
        out.append((p.stem, findings))
    return out


def score_run(gold: Sequence[GoldItem], findings: Sequence[Mapping]) -> dict[str, dict]:
    """Per-dimension counts for one reviewer run: `hits` (a finding whose line falls
    in the anchor range of a same-dimension gold finding), `extra`, and the covered
    gold indices (a finding credits every anchor it lands in)."""
    out: dict[str, dict] = {}
    for f in findings:
        dim = f.get("dimension")
        entry = out.setdefault(dim if isinstance(dim, str) else "", 
                               {"hits": 0, "extra": 0, "covered": set()})
        line = f.get("line")
        hit = [i for i, g in enumerate(gold)
               if g.dimension == dim and isinstance(line, int)
               and g.line_start <= line <= g.line_end]
        if hit:
            entry["hits"] += 1
            entry["covered"].update(hit)
        else:
            entry["extra"] += 1
    return out


def measure(gold_path: Path, runs_dir: Path) -> dict:
    gold = load_gold(gold_path)
    runs = _load_runs(runs_dir)
    per_run = [(name, score_run(gold, findings)) for name, findings in runs]
    dims: list[str] = []
    for g in gold:
        if g.dimension not in dims:
            dims.append(g.dimension)
    for _, score in per_run:
        for dim in score:
            if dim not in dims:
                dims.append(dim)
    out: dict = {"gold": str(gold_path), "runs": [name for name, _ in per_run],
                 "dimensions": {}}
    for dim in sorted(dims):
        items = [i for i, g in enumerate(gold) if g.dimension == dim]
        if dim in _UNMEASURED:
            out["dimensions"][dim] = {"gold": len(items), "verdict": "excluded"}
            continue
        entry: dict = {"gold": len(items),
                       "verdict": "ok" if len(items) >= _NO_VERDICT_MIN else "no_verdict",
                       "runs": {}}
        covered: set[int] = set()
        for name, score in per_run:
            s = score.get(dim)
            hits, extra, found = (s["hits"], s["extra"], s["covered"]) if s else (0, 0, set())
            covered.update(found)
            entry["runs"][name] = {
                "hits": hits, "extra": extra,
                "precision": round(hits / (hits + extra), 3) if hits + extra else None,
                "recall": round(len(found) / len(items), 3) if items else None,
            }
        entry["any_reviewer"] = {
            "found": len(covered),
            "recall": round(len(covered) / len(items), 3) if items else None,
        }
        out["dimensions"][dim] = entry
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Lane measurement: reviewer findings vs a human gold table")
    ap.add_argument("--gold", required=True, help="gold table JSON (items with anchors)")
    ap.add_argument("--runs", required=True, help="directory of sw-review run files")
    ap.add_argument("--out", default=None, help="report path (default: stdout)")
    args = ap.parse_args(argv)
    gold, runs = Path(args.gold), Path(args.runs)
    for p, what in ((gold, "gold table"), (runs, "runs directory")):
        if not p.exists():
            print(f"lane_measure: {what} not found: {p}", file=sys.stderr)
            return 2
    try:
        report = measure(gold, runs)
    except ConfigError as e:
        print(f"lane_measure: ошибка конфигурации — {e}", file=sys.stderr)
        return 3
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
