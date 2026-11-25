"""Hermes bridge for the review ensemble: the review plan becomes ONE delegate_task
batch — a common group, one task per plan dimension, the goal carrying the dimension's
contract bullet and `output_schema` the findings array — and the results are audited
(`schema_valid`, and the route they came back on against the task's lane key). The
model itself is not named here: the profile's `model_map` resolves the lane key
(`sw-fast`/`sw-strong`); when `delegation.backend` is not `model_map`, the caller says
so in the report (`hermes/lanes_check.py` shows the actual assignment).
"""
from __future__ import annotations
from pathlib import Path

from lib.review_plan import ReviewPlan, dimension_contracts

_LANE_KEYS = {"fast": "sw-fast", "strong": "sw-strong"}
_GROUP = "sw-review"
FINDINGS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "file": {"type": "string"},
            "line": {"type": "integer"},
            "dimension": {"type": "string"},
            "severity": {"type": "string", "enum": ["blocker", "warning", "nit"]},
            "problem": {"type": "string"},
            "fix": {"type": "string"},
        },
        "required": ["file", "line", "dimension", "severity", "problem", "fix"],
    },
}


def build_tasks(plan: ReviewPlan, *, root: Path | None = None) -> list[dict]:
    contracts = dimension_contracts(root)
    return [{"id": d.id, "group": _GROUP, "goal": contracts[d.id],
             "model": _LANE_KEYS[d.tier], "output_schema": FINDINGS_SCHEMA}
            for d in plan.dimensions]


def audit_results(tasks: list[dict], results: list[dict]) -> dict:
    lanes = {t["id"]: t["model"] for t in tasks}
    out: dict = {"ok": [], "schema_invalid": [], "route_mismatch": [],
                 "missing": [], "unexpected": []}
    seen: set[str] = set()
    for r in results:
        rid = r.get("id")
        if rid not in lanes:
            out["unexpected"].append(rid)
            continue
        seen.add(rid)
        if not r.get("schema_valid"):
            out["schema_invalid"].append(rid)
        elif r.get("route") != lanes[rid]:
            out["route_mismatch"].append(rid)
        else:
            out["ok"].append(rid)
    out["missing"] = sorted(set(lanes) - seen)
    out["all_ok"] = not (out["schema_invalid"] or out["route_mismatch"]
                         or out["missing"] or out["unexpected"])
    return out
