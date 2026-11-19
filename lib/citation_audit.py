"""Local Quarto bibliography audit: cited keys vs .bib, duplicate identities,
placeholders. No network and no bibtexparser — a deliberately tolerant parser over
the raw .bib text (fields are read as single lines; nested braces inside a field value
may truncate it, which only weakens duplicate detection, never falsifies it). A DOI's
existence online is out of scope on purpose: this audit states only what the local
files themselves contradict."""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from lib.protected_spans import citation_keys

_ENTRY_START_RE = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,")
_FIELD_RE = re.compile(r"^\s*(doi|pmid|title)\s*=\s*[{\"](.+)[}\"]\s*,?\s*$",
                       re.IGNORECASE | re.MULTILINE)
_PLACEHOLDER_RE = re.compile(r"todo|zzz|placeholder|fixme", re.IGNORECASE)
_BIBLIOGRAPHY_RE = re.compile(r"^bibliography:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class AuditFinding:
    category: str  # no-bibliography | missing-key | unused-key | duplicate-doi | duplicate-pmid | duplicate-title | placeholder-entry
    keys: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class BibEntry:
    key: str
    doi: str = ""
    pmid: str = ""
    title: str = ""


def _norm_identity(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def parse_bib(source: str) -> list[BibEntry]:
    entries: list[BibEntry] = []
    starts = list(_ENTRY_START_RE.finditer(source))
    for i, m in enumerate(starts):
        chunk = source[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(source)]
        fields = {k.lower(): v for k, v in _FIELD_RE.findall(chunk)}
        entries.append(BibEntry(
            key=m.group(2),
            doi=_norm_identity(fields.get("doi", "")),
            pmid=_norm_identity(fields.get("pmid", "")),
            title=_norm_identity(fields.get("title", ""))))
    return entries


def find_bibliography(qmd: Path) -> list[Path]:
    """YAML `bibliography:` (file or list), else the single sibling *.bib, else []."""
    m = _BIBLIOGRAPHY_RE.search(qmd.read_text(encoding="utf-8"))
    if m:
        raw = m.group(1).strip()
        names = ([n.strip().strip('"') for n in raw.strip("[]").split(",")]
                 if raw.startswith("[") else [raw])
        return [qmd.parent / n for n in names if n]
    siblings = sorted(qmd.parent.glob("*.bib"))
    return siblings if len(siblings) == 1 else []


def audit(qmd: Path, bibs: list[Path] | None = None) -> list[AuditFinding]:
    cited = citation_keys(qmd.read_text(encoding="utf-8"))
    bibs = bibs if bibs is not None else find_bibliography(qmd)
    if not bibs:
        return [AuditFinding("no-bibliography", (),
                             "no YAML bibliography: and no single sibling .bib")]
    entries: list[BibEntry] = []
    for p in bibs:
        if not p.is_file():
            return [AuditFinding("no-bibliography", (str(p),), f"missing file: {p}")]
        entries += parse_bib(p.read_text(encoding="utf-8"))
    known = {e.key for e in entries}
    findings = [
        AuditFinding("missing-key", (k,), "cited but absent in the bibliography")
        for k in sorted(set(cited) - known)]
    findings += [
        AuditFinding("unused-key", (k,), "in the bibliography, never cited")
        for k in sorted(known - set(cited))]
    for field, category in (("doi", "duplicate-doi"), ("pmid", "duplicate-pmid"),
                            ("title", "duplicate-title")):
        seen: dict[str, list[str]] = {}
        for e in entries:
            value = getattr(e, field)
            if value:
                seen.setdefault(value, []).append(e.key)
        findings += [AuditFinding(category, tuple(sorted(keys)), value)
                     for value, keys in sorted(seen.items()) if len(keys) > 1]
    findings += [
        AuditFinding("placeholder-entry", (e.key,), "placeholder in key or title")
        for e in entries if _PLACEHOLDER_RE.search(e.key + " " + e.title)]
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Local Quarto bibliography audit (advisory, no network)")
    ap.add_argument("doc")
    ap.add_argument("--bib", action="append", default=None,
                    help=".bib path (repeatable); default: YAML bibliography / single sibling")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = Path(args.doc)
    if not doc.is_file():
        print(f"file not found: {doc}", file=sys.stderr)
        return 2
    bibs = [Path(p) for p in args.bib] if args.bib else None
    findings = audit(doc, bibs)
    if args.json:
        print(json.dumps([asdict(f) | {"keys": list(f.keys)} for f in findings],
                         ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"{f.category:20} {', '.join(f.keys)}  {f.detail}")
        print(f"{len(findings)} finding(s)", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
