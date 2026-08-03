"""Deterministic calque linter for Quarto .qmd prose. Stdlib only."""
from __future__ import annotations
import argparse, json, re, subprocess, sys
from dataclasses import dataclass, asdict
from pathlib import Path

from lib import checks as check_registry
from lib.document import Document
from lib.morph import Morph
from lib.qmd_prose import extract_prose

_CANON = Path(__file__).resolve().parents[1] / "canon"
_DEFAULT_DICT = _CANON / "dictionary.json"
_ORTHO_DICT = _CANON / "orthography.json"
_LOCAL_RELPATH = Path(".claude") / "scientific-writing" / "dictionary.json"
_GIT_ROOT_CACHE: dict[str, "Path | None"] = {}
_SEVERITIES = {"error", "warn", "info"}
_KINDS = {"regex", "check"}


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


def _read(p: Path) -> list[dict]:
    return json.loads(p.read_text(encoding="utf-8"))["entries"]


def load_entries(path: str | None) -> list[dict]:
    """Regex-kind entries, compiled. Callers (`lib.tune_diff`, tests) rely on `_rx`."""
    files = [Path(path)] if path else [_DEFAULT_DICT, _ORTHO_DICT]
    out: list[dict] = []
    for p in files:
        for e in _read(p):
            if e.get("kind", "regex") != "regex":
                continue
            e["_rx"] = re.compile(e["pattern"], re.IGNORECASE | re.UNICODE)
            out.append(e)
    return out


def load_check_entries(path: str | None = None) -> list[dict]:
    """Check-kind entries. `id` must name a check registered in `lib.checks`."""
    files = [Path(path)] if path else [_DEFAULT_DICT, _ORTHO_DICT]
    out: list[dict] = []
    for p in files:
        for e in _read(p):
            if e.get("kind") == "check":
                out.append(e)
    return out


def load_raw(path: Path, base_ids: frozenset[str] = frozenset()) -> list[dict]:
    """Load + validate a project-local dictionary; compile `_rx` on non-disabled entries.

    An entry whose id already exists in the base is a *partial* override: it inherits every
    field it omits, so a project can add an `allow` wordlist to `ortho-spelling` without
    restating its severity, message and pattern.
    """
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
        disabled = e.get("disabled")
        if disabled is not None and not isinstance(disabled, bool):
            raise ConfigError(f"{path}: правило «{eid}» — «disabled» должно быть булевым")
        if disabled:
            continue
        # A project overlay usually just adds an `allow` list to a check; inferring the kind
        # from the registry saves it from having to repeat `"kind": "check"`.
        kind = e.get("kind") or ("check" if check_registry.get(eid) else "regex")
        e["kind"] = kind
        if kind not in _KINDS:
            raise ConfigError(f"{path}: правило «{eid}» — недопустимый «kind» «{kind}»: "
                              f"ожидается {', '.join(sorted(_KINDS))}")
        required = ("severity", "message") if kind == "check" else ("pattern", "severity", "message")
        if eid in base_ids:
            required = tuple(k for k in required if k in e)  # partial override inherits the rest
        missing = [k for k in required if not e.get(k)]
        if missing:
            raise ConfigError(f"{path}: правило «{eid}» без обязательных полей: {', '.join(missing)}")
        for k in required:
            if not isinstance(e[k], str):
                raise ConfigError(f"{path}: правило «{eid}» — поле «{k}» должно быть строкой")
        if "severity" in e and e["severity"] not in _SEVERITIES:
            raise ConfigError(
                f"{path}: правило «{eid}» — недопустимая severity «{e['severity']}»: "
                f"ожидается {', '.join(sorted(_SEVERITIES))}")
        exc = e.get("except")
        if exc is not None and not isinstance(exc, str):
            raise ConfigError(f"{path}: правило «{eid}» — «except» должно быть строкой")
        allow = e.get("allow")
        if allow is not None and not (isinstance(allow, list) and all(isinstance(x, str) for x in allow)):
            raise ConfigError(f"{path}: правило «{eid}» — «allow» должно быть списком строк")
        degraded = e.get("severity_without_morph")
        if degraded is not None and degraded not in _SEVERITIES:
            # Under the hook's system python3 this *is* the gate severity: a typo here would
            # silently turn an error into a pass.
            raise ConfigError(
                f"{path}: правило «{eid}» — недопустимая severity_without_morph «{degraded}»: "
                f"ожидается {', '.join(sorted(_SEVERITIES))}")
        freq = e.get("term_frequency")
        if freq is not None and (isinstance(freq, bool) or not isinstance(freq, int)):
            raise ConfigError(f"{path}: правило «{eid}» — «term_frequency» должно быть целым числом")
        if kind == "check":
            if check_registry.get(eid) is None:
                raise ConfigError(f"{path}: правило «{eid}» — нет такой проверки; доступны: "
                                  f"{', '.join(sorted(check_registry.known_ids()))}")
            continue
        if "pattern" not in e:
            continue  # partial override of a regex rule — the base pattern stands
        try:
            e["_rx"] = re.compile(e["pattern"], re.IGNORECASE | re.UNICODE)
        except (re.error, TypeError) as err:
            raise ConfigError(f"{path}: правило «{eid}» — некорректный паттерн: {err}") from err
    return data["entries"]


def merge_entries(base: list[dict], local: list[dict]) -> list[dict]:
    """Effective rule set: base ⊕ local. Local upserts by id; `disabled` drops an id.

    An override merges field-wise, so omitted fields keep their base values — that is what
    lets a project add only an `allow` list to a check rule.
    """
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
    result = [_apply_override(e, overrides[e["id"]]) if e["id"] in overrides else e
              for e in base if e["id"] not in disabled]
    result.extend(extra)
    return result


def _apply_override(base: dict, local: dict) -> dict:
    merged = {**base, **local}
    if "pattern" in local and "_rx" not in local:
        merged.pop("_rx", None)  # never keep a compiled regex from a superseded pattern
    return merged


def partition_kinds(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split into (regex, check). A `disabled` marker has no kind, so it joins both sides
    and drops its id from whichever base list holds it."""
    regex, check = [], []
    for e in entries:
        if e.get("disabled"):
            regex.append(e)
            check.append(e)
        elif e.get("kind") == "check":
            check.append(e)
        else:
            regex.append(e)
    return regex, check


def lint_text(source: str, entries: list[dict], file: str = "<text>") -> list[Finding]:
    """Regex entries against every prose line. All matches on a line, not just the first."""
    findings: list[Finding] = []
    for pl in extract_prose(source):
        for e in entries:
            if e["id"] in pl.suppress:
                continue
            exc = e.get("except")
            if exc and exc.lower() in pl.text.lower():
                continue
            for m in e["_rx"].finditer(pl.text):
                findings.append(Finding(file, pl.lineno, m.start() + 1, e["id"],
                                        e["severity"], e["message"], m.group(0)))
    return findings


def run_checks(doc: Document, check_entries: list[dict], morph: Morph) -> list[Finding]:
    """Code checks against the document. Severity/message come from the entry, so a
    project overlay can demote or mute a check exactly like a regex rule."""
    findings: list[Finding] = []
    for e in check_entries:
        fn = check_registry.get(e["id"])
        if fn is None:
            continue
        severity = _effective_severity(e, morph)
        exc = (e.get("except") or "").lower()
        for hit in fn(doc, morph, e):
            if doc.is_suppressed(hit.lineno, e["id"]):
                continue
            if exc and exc in doc.line_text(hit.lineno).lower():
                continue
            message = f"{e['message']} — {hit.detail}" if hit.detail else e["message"]
            findings.append(Finding(doc.path, hit.lineno, hit.col, e["id"],
                                    severity, message, hit.matched))
    return findings


def _effective_severity(entry: dict, morph: Morph) -> str:
    """`severity_without_morph` demotes a rule whose precision depends on the dictionary."""
    if not morph.available and entry.get("severity_without_morph"):
        return entry["severity_without_morph"]
    return entry["severity"]


def lint_source(source: str, entries: list[dict], check_entries: list[dict],
                morph: Morph, file: str = "<text>") -> list[Finding]:
    doc = Document.from_source(source, path=file)
    return lint_text(source, entries, file) + run_checks(doc, check_entries, morph)


def lint_file(path: str, entries: list[dict], changed: set[int] | None = None,
              check_entries: list[dict] | None = None,
              morph: Morph | None = None) -> list[Finding]:
    src = Path(path).read_text(encoding="utf-8")
    fs = lint_source(src, entries, check_entries or [], morph or Morph(available=False), file=path)
    if changed is not None:
        fs = [f for f in fs if f.line in changed]
    return sorted(fs, key=lambda f: (f.line, f.col, f.id))


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


def _git_root(start: Path) -> Path | None:
    key = str(start)
    if key in _GIT_ROOT_CACHE:
        return _GIT_ROOT_CACHE[key]
    try:
        out = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=False)
        root = Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except OSError:
        root = None
    _GIT_ROOT_CACHE[key] = root
    return root


def local_dict_path(target: str | Path) -> Path | None:
    root = _git_root(Path(target).resolve().parent)
    return root / _LOCAL_RELPATH if root else None


def _resolve_local(target: str, forced: str | None, use_local: bool,
                   cache: dict[str, list[dict]],
                   base_ids: frozenset[str] = frozenset()) -> list[dict]:
    if not use_local:
        return []
    if forced:
        p: Path | None = Path(forced)
        if not p.exists():
            raise ConfigError(f"{forced}: файл локального словаря не найден")
    else:
        p = local_dict_path(target)
        if p is None or not p.exists():
            return []
    key = str(p.resolve())
    if key not in cache:
        cache[key] = load_raw(p, base_ids)
    return cache[key]


def _degraded_note(check_entries: list[dict]) -> str:
    """Derived from the entries, so a new morphology-dependent check cannot make it stale."""
    demoted = [e["id"] for e in check_entries if e.get("severity_without_morph")]
    skipped = [e["id"] for e in check_entries
               if not e.get("severity_without_morph") and check_registry.needs_morph(e["id"])]
    parts = ["lint_prose: без морфологии (pip install -e '.[morph]')"]
    if skipped:
        parts.append(f"проверки {', '.join(sorted(skipped))} пропущены")
    if demoted:
        parts.append(f"{', '.join(sorted(demoted))} работает в ослабленном режиме")
    return " — ".join(parts) + "."


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
    ap.add_argument("--local-dictionary", default=None,
                    help="use this file as the project-local dictionary (overrides auto-discovery)")
    ap.add_argument("--no-local", action="store_true",
                    help="ignore any project-local dictionary")
    ap.add_argument("--no-morph", action="store_true",
                    help="ignore the optional morphology extra (checks skip or demote)")
    args = ap.parse_args(argv)
    base = load_entries(args.dictionary)
    base_checks = load_check_entries(args.dictionary)
    morph = Morph(available=False) if args.no_morph else Morph.load()
    local_cache: dict[str, list[dict]] = {}
    base_ids = frozenset(e["id"] for e in base) | frozenset(e["id"] for e in base_checks)
    findings: list[Finding] = []
    try:
        for f in args.files:
            local = _resolve_local(f, args.local_dictionary, not args.no_local, local_cache,
                                   base_ids)
            local_rx, local_ck = partition_kinds(local)
            entries = merge_entries(base, local_rx) if local else base
            check_entries = merge_entries(base_checks, local_ck) if local else base_checks
            changed = None
            if args.diff is not None:
                ref = None if args.diff == "__staged__" else args.diff
                changed = changed_lines(f, ref)
            findings += lint_file(f, entries, changed, check_entries, morph)
    except ConfigError as e:
        print(f"lint_prose: ошибка локального словаря {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps([asdict(x) for x in findings], ensure_ascii=False, indent=2))
    else:
        print(_format_text(findings))
    if not morph.available:
        # stderr, so the stdout contract (a flat findings array) stays what
        # /text-review and /tune-draft already parse.
        print(_degraded_note(base_checks), file=sys.stderr)
    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
