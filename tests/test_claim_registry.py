"""Claim/number registries: schema validation + cross-check against the document.
Registries are optional sidecars filled by the writer/reviewer; this module states
only what the local files themselves contradict."""
import json

from lib.claim_registry import check_document, main

DOC_TEXT = ("Медиана выживаемости составила 92 % (n = 40). По данным [@ivanov2020], "
            "метод превосходит контроль.\n")


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_happy_path_is_silent(tmp_path):
    doc = write(tmp_path, "doc.qmd", DOC_TEXT)
    claims = write(tmp_path, "doc.claims.jsonl",
                   json.dumps({"claim_id": "c1", "section": "Results",
                               "claim_kind": "headline",
                               "evidence": "tbl:survival",
                               "citation_keys": ["ivanov2020"],
                               "support_status": "supported"}, ensure_ascii=False) + "\n")
    numbers = write(tmp_path, "doc.numbers.json", json.dumps({"records": [
        {"value": "92", "unit": "%", "source": "tbl:survival",
         "used_in": ["Results"]}]}, ensure_ascii=False))
    assert check_document(doc, claims, numbers) == []


def test_schema_violations_reported(tmp_path):
    doc = write(tmp_path, "doc.qmd", DOC_TEXT)
    claims = write(tmp_path, "doc.claims.jsonl", json.dumps({
        "claim_id": "c1", "section": "Results", "claim_kind": "wow",
        "evidence": "x", "citation_keys": [], "support_status": "fine"}) + "\n")
    numbers = write(tmp_path, "doc.numbers.json", json.dumps({"records": [
        {"value": "92,5%", "unit": "", "source": ""}]}))
    cats = {f.category for f in check_document(doc, claims, numbers)}
    assert "schema" in cats


def test_cross_check_findings(tmp_path):
    doc = write(tmp_path, "doc.qmd", DOC_TEXT)
    claims = write(tmp_path, "doc.claims.jsonl", json.dumps({
        "claim_id": "c1", "section": "Results", "claim_kind": "headline",
        "evidence": "tbl:survival", "citation_keys": ["nosuchkey2020"],
        "support_status": "unsupported"}) + "\n")
    numbers = write(tmp_path, "doc.numbers.json", json.dumps({"records": [
        {"value": "78", "unit": "%", "source": "tbl:survival", "used_in": []}]}))
    cats = {(f.category, f.ref) for f in check_document(doc, claims, numbers)}
    assert ("uncited-key", "c1") in cats
    assert ("unknown-number", "78%") in cats
    assert ("unsupported-claim", "c1") in cats


def test_no_registries_is_silence(tmp_path):
    doc = write(tmp_path, "doc.qmd", DOC_TEXT)
    assert check_document(doc, None, None) == []
    assert main([str(doc), "--json"]) == 0


def test_cli_exit_codes(tmp_path):
    doc = write(tmp_path, "doc.qmd", DOC_TEXT)
    claims = write(tmp_path, "doc.claims.jsonl", json.dumps({
        "claim_id": "c1", "section": "R", "claim_kind": "causal",
        "evidence": "x", "citation_keys": [],
        "support_status": "unsupported"}) + "\n")
    assert main([str(doc), "--claims", str(claims), "--json"]) == 1
    assert main([str(tmp_path / "nope.qmd")]) == 2


def test_explicit_missing_registry_path_exits_2(tmp_path):
    doc = write(tmp_path, "doc.qmd", DOC_TEXT)
    assert main([str(doc), "--claims", str(tmp_path / "nope.jsonl"), "--json"]) == 2
    assert main([str(doc), "--numbers", str(tmp_path / "nope.json"), "--json"]) == 2


def test_non_object_claims_rows_are_schema_findings(tmp_path):
    doc = write(tmp_path, "doc.qmd", DOC_TEXT)
    claims = write(tmp_path, "doc.claims.jsonl", "[1, 2]\nnull\n")
    findings = check_document(doc, claims, None)
    assert len(findings) == 2
    assert all(f.category == "schema" and f.ref.startswith("line:") for f in findings)


def test_malformed_numbers_are_schema_findings(tmp_path):
    doc = write(tmp_path, "doc.qmd", DOC_TEXT)
    cases = ["[1, 2]", '{"records": 5}',
             json.dumps({"records": ["92", {"value": "bad%", "unit": "", "source": ""}]})]
    for text in cases:
        numbers = write(tmp_path, "doc.numbers.json", text)
        findings = check_document(doc, None, numbers)
        assert {f.category for f in findings} == {"schema"}, text
