"""Read-only lanes check for Hermes: which model actually serves each role. Prints the
«роль — объявленная полоса — фактическая модель» table from a profile's
`delegation.backend` and `model_map` and writes nothing. When the backend is not
`model_map`, the table says so — the advanced-delegation plugin may be absent, and
then no model is assigned by lane at all. A missing `model_map` entry shows as «—».

    PYTHONPATH=$REPO $REPO/.venv/bin/python $REPO/hermes/lanes_check.py [--profile NAME|PATH]
"""
from __future__ import annotations
import argparse
import re
from pathlib import Path

from lib.lanes import load_lanes
from lib.review_plan import load_registry

REPO = Path(__file__).resolve().parents[1]
_HERMES_HOME = Path.home() / ".hermes"


def profile_config(name: str | None) -> Path | None:
    if name is None:
        p = _HERMES_HOME / "config.yaml"
    else:
        p = Path(name)
        if p.is_dir():
            p = p / "config.yaml"
        elif not p.is_file():
            p = _HERMES_HOME / "profiles" / name / "config.yaml"
    return p if p.is_file() else None


def _delegation_block(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    active = False
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()
        if indent == 0 and re.match(r"^delegation:\s*(?:#.*)?$", stripped):
            active = True
            continue
        if active:
            if indent == 0:
                break
            out.append((indent, stripped))
    return out


def delegation_settings(text: str) -> tuple[str, dict[str, str]]:
    """The `backend:` value and the flat scalar entries of `model_map:` inside the
    profile's `delegation:` block — a narrow scan, no YAML dependency."""
    block = _delegation_block(text)
    if not block:
        return "", {}
    base = block[0][0]
    backend = ""
    for indent, stripped in block:
        if indent == base:
            m = re.match(r"^backend:\s*([^\s#]+)", stripped)
            if m:
                backend = m.group(1)
    model_map: dict[str, str] = {}
    map_indent = None
    for indent, stripped in block:
        if map_indent is not None:
            if indent <= map_indent:
                map_indent = None
            else:
                m = re.match(r"^([\w.-]+):\s*([^\s#]+)\s*$", stripped)
                if m:
                    model_map[m.group(1)] = m.group(2)
                continue
        if re.match(r"^model_map:\s*(?:#.*)?$", stripped):
            map_indent = indent
    return backend, model_map


def _mapped(lane: str, model_map: dict[str, str]) -> str:
    if lane in model_map:
        return model_map[lane]
    if f"sw-{lane}" in model_map:
        return model_map[f"sw-{lane}"]
    return "—"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Lanes check: role — declared lane — actual model (read-only)")
    ap.add_argument("--profile", default=None,
                    help="profile name or config path (default: the default profile)")
    args = ap.parse_args(argv)
    lanes = load_lanes()
    cfg = profile_config(args.profile)
    backend, model_map = ("", {}) if cfg is None \
        else delegation_settings(cfg.read_text(encoding="utf-8"))
    is_map = backend == "model_map"
    rows: list[tuple[str, str, str]] = [
        ("writer", lanes.writer, _mapped(lanes.writer, model_map) if is_map else "—"),
        ("judge", lanes.judge, _mapped(lanes.judge, model_map) if is_map else "—"),
    ]
    rows += [(e["id"], e["tier"], model_map.get(f"sw-{e['tier']}", "—") if is_map else "—")
             for e in load_registry()]
    if not is_map:
        rows.insert(0, ("delegation.backend", "—",
                        f"{backend or 'не задан'} — не model_map, назначение не активно"))
    print(f"профиль: {cfg or 'не найден'}")
    width = max(len(r[0]) for r in rows)
    print(f"{'роль':<{width}}  полоса              фактическая модель")
    for role, lane, model in rows:
        print(f"{role:<{width}}  {lane:<18}  {model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
