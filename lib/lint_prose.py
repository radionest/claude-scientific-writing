"""Deterministic calque linter for Quarto .qmd prose. Stdlib only."""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from dataclasses import dataclass, asdict
from pathlib import Path

from lib.qmd_prose import extract_prose

_DEFAULT_DICT = Path(__file__).resolve().parents[1] / "canon" / "dictionary.json"


class ConfigError(Exception):
    """Malformed project-local dictionary."""


@dataclass
class Finding:
    file: str
    line: int
    col: int
    id: str
    severity: str
    message: str
    matched: str


def load_entries(path: str | None) -> list[dict]:
    p = Path(path) if path else _DEFAULT_DICT
    data = json.loads(p.read_text(encoding="utf-8"))
    for e in data["entries"]:
        e["_rx"] = re.compile(e["pattern"], re.IGNORECASE | re.UNICODE)
    return data["entries"]


def load_raw(path: Path) -> list[dict]:
    """Load + validate a project-local dictionary; compile `_rx` on non-disabled entries."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"{path}: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise ConfigError(f"{path}: ожидается объект с полем «entries» (список)")
    seen: set[str] = set()
    for e in data["entries"]:
        if not isinstance(e, dict):
            raise ConfigError(f"{path}: запись не является объектом")
        eid = e.get("id")
        if not isinstance(eid, str) or not eid:
            raise ConfigError(f"{path}: запись без строкового «id»")
        if eid in seen:
            raise ConfigError(f"{path}: повтор id «{eid}»")
        seen.add(eid)
        if e.get("disabled"):
            continue
        missing = [k for k in ("pattern", "severity", "message") if not e.get(k)]
        if missing:
            raise ConfigError(f"{path}: правило «{eid}» без обязательных полей: {', '.join(missing)}")
        try:
            e["_rx"] = re.compile(e["pattern"], re.IGNORECASE | re.UNICODE)
        except (re.error, TypeError) as err:
            raise ConfigError(f"{path}: правило «{eid}» — некорректный паттерн: {err}") from err
    return data["entries"]


def merge_entries(base: list[dict], local: list[dict]) -> list[dict]:
    """Effective rule set: base ⊕ local. Local upserts by id; `disabled` drops an id."""
    overrides: dict[str, dict] = {}
    disabled: set[str] = set()
    extra: list[dict] = []
    base_ids = {e["id"] for e in base}
    for e in local:
        eid = e["id"]
        if e.get("disabled"):
            disabled.add(eid)
        elif eid in base_ids:
            overrides[eid] = e
        else:
            extra.append(e)
    result = [overrides.get(e["id"], e) for e in base if e["id"] not in disabled]
    result.extend(extra)
    return result


def lint_text(source: str, entries: list[dict], file: str = "<text>") -> list[Finding]:
    findings: list[Finding] = []
    for pl in extract_prose(source):
        for e in entries:
            if e["id"] in pl.suppress:
                continue
            exc = e.get("except")
            if exc and exc.lower() in pl.text.lower():
                continue
            m = e["_rx"].search(pl.text)
            if m:
                findings.append(Finding(file, pl.lineno, m.start() + 1, e["id"],
                                        e["severity"], e["message"], m.group(0)))
    return findings


def lint_file(path: str, entries: list[dict], changed: set[int] | None = None) -> list[Finding]:
    src = Path(path).read_text(encoding="utf-8")
    fs = lint_text(src, entries, file=path)
    if changed is not None:
        fs = [f for f in fs if f.line in changed]
    return fs


def changed_lines(path: str, ref: str | None) -> set[int]:
    """New-side line numbers added/modified for `path` vs ref (or staged if ref is None)."""
    cmd = ["git", "diff", "--unified=0", "--no-color"]
    cmd += [ref, "--", path] if ref else ["--cached", "--", path]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False).stdout
    except OSError:
        return set()
    changed: set[int] = set()
    new = 0
    for line in out.splitlines():
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                new = int(m.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            changed.add(new)
            new += 1
        elif not line.startswith("-"):
            new += 1
    return changed


def _format_text(findings: list[Finding]) -> str:
    if not findings:
        return "lint_prose: чисто."
    rows = [f"{f.file}:{f.line}:{f.col} [{f.severity}] {f.id} — {f.message}  «{f.matched}»"
            for f in findings]
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Calque linter for .qmd prose")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--diff", nargs="?", const="__staged__", default=None,
                    help="lint only changed lines; optional REF (default: staged)")
    ap.add_argument("--dictionary", default=None)
    args = ap.parse_args(argv)
    entries = load_entries(args.dictionary)
    findings: list[Finding] = []
    for f in args.files:
        changed = None
        if args.diff is not None:
            ref = None if args.diff == "__staged__" else args.diff
            changed = changed_lines(f, ref)
        findings += lint_file(f, entries, changed)
    if args.json:
        print(json.dumps([asdict(x) for x in findings], ensure_ascii=False, indent=2))
    else:
        print(_format_text(findings))
    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
