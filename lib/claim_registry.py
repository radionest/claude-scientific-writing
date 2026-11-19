"""Optional claim/number registries for a full article: schema validation plus a
cross-check against the document. Filled by the writer/reviewer (judgment); this
module states only what the local files themselves contradict — an unsupported claim
being published, a registry key never cited, a registered number absent from the
text. `needs_human` is a valid status, not a finding: an inaccessible full text is
not evidence against a source."""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lib.protected_spans import citation_keys
from lib.revision_guard import number_keys

CLAIM_KINDS = {"headline", "causal", "methodological", "descriptive", "null-result"}
SUPPORT_STATUSES = {"supported", "needs_human", "unsupported", "not_checked"}
_VALUE_RE = re.compile(r"[-+]?\d+(?:\.\d+)?$")


@dataclass(frozen=True, slots=True)
class RegistryFinding:
    category: str  # schema | uncited-key | unknown-number | unsupported-claim
    ref: str
    detail: str


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: str
    section: str
    claim_kind: str
    evidence: str
    citation_keys: tuple[str, ...]
    support_status: str


@dataclass(frozen=True, slots=True)
class NumberRecord:
    value: str
    unit: str = ""
    population: str = ""
    analysis_set: str = ""
    uncertainty: str = ""
    source: str = ""
    used_in: tuple[str, ...] = field(default_factory=tuple)


def _schema(detail: str, ref: str) -> RegistryFinding:
    return RegistryFinding("schema", ref, detail)


def load_claims(path: Path) -> tuple[list[Claim], list[RegistryFinding]]:
    claims: list[Claim] = []
    findings: list[RegistryFinding] = []
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            findings.append(_schema(f"line {lineno}: invalid JSON ({e})", f"line:{lineno}"))
            continue
        missing = ({"claim_id", "section", "claim_kind", "evidence",
                    "citation_keys", "support_status"} - set(row))
        if missing:
            findings.append(_schema(f"line {lineno}: missing {sorted(missing)}",
                                    str(row.get("claim_id", f"line:{lineno}"))))
            continue
        if row["claim_kind"] not in CLAIM_KINDS or row["support_status"] not in SUPPORT_STATUSES:
            findings.append(_schema(
                f"line {lineno}: claim_kind/support_status out of enum", row["claim_id"]))
            continue
        claims.append(Claim(row["claim_id"], row["section"], row["claim_kind"],
                            row["evidence"], tuple(row["citation_keys"]),
                            row["support_status"]))
    return claims, findings


def load_numbers(path: Path) -> tuple[list[NumberRecord], list[RegistryFinding]]:
    findings: list[RegistryFinding] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data["records"]
    except (json.JSONDecodeError, KeyError) as e:
        return [], [_schema(f"invalid numbers.json ({e})", path.name)]
    records: list[NumberRecord] = []
    for i, row in enumerate(rows):
        missing = ({"value", "unit", "source"} - set(row))
        if missing or not _VALUE_RE.match(str(row.get("value", ""))):
            findings.append(_schema(
                f"record {i}: value/unit/source required, value numeric like '92'",
                str(row.get("value", f"record:{i}"))))
            continue
        records.append(NumberRecord(
            value=str(row["value"]), unit=str(row.get("unit", "")),
            population=str(row.get("population", "")),
            analysis_set=str(row.get("analysis_set", "")),
            uncertainty=str(row.get("uncertainty", "")),
            source=str(row.get("source", "")),
            used_in=tuple(row.get("used_in", ()))))
    return records, findings


def check_document(doc: Path, claims_path: Path | None,
                   numbers_path: Path | None) -> list[RegistryFinding]:
    source = doc.read_text(encoding="utf-8")
    findings: list[RegistryFinding] = []
    doc_keys = set(citation_keys(source))
    doc_numbers = number_keys(source)
    if claims_path is not None:
        claims, findings = load_claims(claims_path)
        for c in claims:
            for key in c.citation_keys:
                if key not in doc_keys:
                    findings.append(RegistryFinding(
                        "uncited-key", c.claim_id,
                        f"{key}: registry key not cited in the document"))
            if c.support_status == "unsupported":
                findings.append(RegistryFinding(
                    "unsupported-claim", c.claim_id,
                    "claim is published while marked unsupported"))
    if numbers_path is not None:
        records, number_findings = load_numbers(numbers_path)
        findings += number_findings
        for r in records:
            key = r.value + ("%" if r.unit == "%" else "")
            if doc_numbers.get(key, 0) < 1:
                findings.append(RegistryFinding(
                    "unknown-number", key,
                    "registered number not found in the document"))
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate optional claim/number registries against the document (advisory)")
    ap.add_argument("doc")
    ap.add_argument("--claims", default=None)
    ap.add_argument("--numbers", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    doc = Path(args.doc)
    if not doc.is_file():
        print(f"file not found: {doc}", file=sys.stderr)
        return 2
    claims_path = (Path(args.claims) if args.claims else doc.with_suffix(".claims.jsonl"))
    numbers_path = (Path(args.numbers) if args.numbers else doc.with_suffix(".numbers.json"))
    if not claims_path.is_file() and not numbers_path.is_file():
        return 0  # registries are optional — silence is a valid state
    findings = check_document(
        doc,
        claims_path if claims_path.is_file() else None,
        numbers_path if numbers_path.is_file() else None)
    if args.json:
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f"{f.category:19} {f.ref}: {f.detail}")
        print(f"{len(findings)} finding(s)", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
