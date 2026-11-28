"""Read-only lanes check for ZCode: which model actually serves each role. Reads the
user's agent pinning (Settings → Subagents — it wins over the agent definition) and
the `model:` pseudo-alias in the agents' frontmatter, which does not set the model;
the sw-review workflow passes explicit models per lane at launch. Prints the
«роль — объявленная полоса — фактическая модель» table and writes nothing.

    PYTHONPATH=$REPO $REPO/.venv/bin/python $REPO/.zcode/scripts/lanes_check.py
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from lib.lanes import load_lanes
from lib.review_plan import load_registry

REPO = Path(__file__).resolve().parents[2]
_STATE = Path.home() / ".zcode" / "v2" / "agents-state.json"
_AGENT_FILES = {"fast": "prose-reviewer.md", "strong": "prose-reviewer-strong.md"}


def _pinned() -> dict[str, str]:
    """Agent name → the pinned model (`provider/model$level`), from the subagent
    pinning state; an unreadable or absent state file simply means no pins."""
    try:
        data = json.loads(_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for key, val in data.get("pluginAgentModelSelectionOverrides", {}).items():
        if not isinstance(val, dict) or not val.get("modelId"):
            continue
        model = f"{val.get('providerId', '?')}/{val['modelId']}"
        level = (val.get("options") or {}).get("reasoningLevel")
        out[key.rsplit(":", 1)[-1]] = f"{model}${level}" if level else model
    return out


def _frontmatter_alias(agent_file: Path) -> str:
    m = re.match(r"(?s)^---\n(.*?)\n---", agent_file.read_text(encoding="utf-8"))
    if not m:
        return ""
    a = re.search(r"(?m)^model:\s*(\S.*)$", m.group(1))
    return a.group(1).strip() if a else ""


def main() -> int:
    pins = _pinned()
    lanes = load_lanes()
    agents = REPO / "agents"

    def actual(name: str, agent_file: str) -> str:
        if name in pins:
            return pins[name]
        alias = _frontmatter_alias(agents / agent_file)
        return f"{alias} (псевдоним frontmatter, модель не задаёт)" if alias else "—"

    rows = [("writer", lanes.writer, actual("scientific-writer", "scientific-writer.md")),
            ("judge", lanes.judge, actual("prose-reviewer-strong", "prose-reviewer-strong.md"))]
    rows += [(e["id"], e["tier"],
              actual(_AGENT_FILES[e["tier"]].removesuffix(".md"), _AGENT_FILES[e["tier"]]))
             for e in load_registry()]
    width = max(len(r[0]) for r in rows)
    print(f"{'роль':<{width}}  полоса              фактическая модель")
    for role, lane, model in rows:
        print(f"{role:<{width}}  {lane:<18}  {model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
