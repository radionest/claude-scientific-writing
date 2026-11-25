"""Jev judges: transport choice, the status contract and the pilot CLI — no network,
`urllib.request.urlopen` is stubbed with fixtures.

THEORY (docs, not recorded): the recorded-response fixture below is composed from
the TypeSafe API docs (https://docs.typesafe.ai) and the OpenRouter Decisions
endpoint description — no OPENROUTER_API_KEY / TYPESAFE_API_KEY was available to
capture a live payload, so the wire contract is pinned to the documented shape,
not to a recorded response.
"""
import http.client
import io
import json
import urllib.error
import urllib.request

import pytest

from lib.judges import _resolve_transport, main, run_judge

_RECORDED = {
    "answers": {
        "meaning-kept": {"type": "noul", "value": 0.93},
        "new-claim": {"type": "noul", "value": 0.04},
    },
    "usage": {"input_tokens": 612},
}

_STATE = {"before": "Метод точен и воспроизводим.", "after": "Метод точен."}


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install(monkeypatch, payload=None, raw=None, error=None):
    sent = []

    def fake_urlopen(request, timeout=None):
        sent.append(request)
        if error is not None:
            raise error
        body = raw if raw is not None else json.dumps(
            payload if payload is not None else _RECORDED,
            ensure_ascii=False).encode("utf-8")
        return _FakeResponse(body)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return sent


def _env(monkeypatch, openrouter=None, typesafe=None, transport=None):
    for var, value in (("OPENROUTER_API_KEY", openrouter),
                       ("TYPESAFE_API_KEY", typesafe),
                       ("SW_JUDGE__TRANSPORT", transport)):
        if value is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, value)


def test_recorded_response_is_ok(monkeypatch):
    _env(monkeypatch, openrouter="k")
    sent = _install(monkeypatch)
    result = run_judge("edit-fidelity", _STATE)
    assert result.status == "ok"
    assert result.answers == {"meaning-kept": 0.93, "new-claim": 0.04}
    assert result.usage == {"input_tokens": 612}
    assert result.elapsed_ms >= 0
    request = sent[0]
    assert request.full_url == "https://openrouter.ai/api/alpha/decisions"
    assert request.get_header("Authorization") == "Bearer k"
    payload = json.loads(request.data)
    assert payload["model"] == "typesafe/jev-1.14"
    assert set(payload["state"]) == {"before", "after"}
    assert set(payload["questions"]) == {"meaning-kept", "new-claim"}
    assert all(q["type"] == "noul" for q in payload["questions"].values())


def test_refusal_is_refused(monkeypatch):
    _env(monkeypatch, openrouter="k")
    _install(monkeypatch, payload={
        "answers": {"meaning-kept": {"type": "refusal"},
                    "new-claim": {"type": "noul", "value": 0.1}},
        "usage": {"input_tokens": 300}})
    result = run_judge("edit-fidelity", _STATE)
    assert result.status == "refused"
    assert result.answers == {"new-claim": 0.1}
    assert result.usage == {"input_tokens": 300}


def test_http_500_is_error(monkeypatch):
    _env(monkeypatch, openrouter="k")
    _install(monkeypatch, error=urllib.error.HTTPError(
        "https://openrouter.ai/api/alpha/decisions", 500, "Internal Server Error",
        None, io.BytesIO(b"")))
    result = run_judge("edit-fidelity", _STATE)
    assert result.status == "error"
    assert result.answers == {}
    assert result.usage == {}


def test_truncated_response_is_error(monkeypatch):
    # IncompleteRead is an http.client.HTTPException, not an OSError — it must not
    # escape run_judge and abort the pilot batch mid-run
    _env(monkeypatch, openrouter="k")
    _install(monkeypatch, error=http.client.IncompleteRead(b"partial", 1200))
    result = run_judge("edit-fidelity", _STATE)
    assert result.status == "error"
    assert result.answers == {}


def test_malformed_response_is_error(monkeypatch):
    _env(monkeypatch, openrouter="k")
    _install(monkeypatch, raw=b"{not json")
    assert run_judge("edit-fidelity", _STATE).status == "error"
    _install(monkeypatch, payload={"no_answers_key": {}})
    assert run_judge("edit-fidelity", _STATE).status == "error"


@pytest.mark.parametrize("env,expected", [
    ({}, None),
    ({"OPENROUTER_API_KEY": "or"}, "openrouter"),
    ({"TYPESAFE_API_KEY": "ts"}, "typesafe"),
    ({"OPENROUTER_API_KEY": "or", "TYPESAFE_API_KEY": "ts"}, "openrouter"),
    ({"SW_JUDGE__TRANSPORT": "openrouter", "OPENROUTER_API_KEY": "or"}, "openrouter"),
    ({"SW_JUDGE__TRANSPORT": "typesafe", "TYPESAFE_API_KEY": "ts"}, "typesafe"),
    ({"SW_JUDGE__TRANSPORT": "typesafe"}, None),
    ({"SW_JUDGE__TRANSPORT": "unknown", "OPENROUTER_API_KEY": "or"}, None),
])
def test_transport_selected_from_environment(monkeypatch, env, expected):
    _env(monkeypatch)
    for var, value in env.items():
        monkeypatch.setenv(var, value)
    resolved = _resolve_transport()
    assert (resolved[0] if resolved else None) == expected


def test_typesafe_endpoint_used_when_selected(monkeypatch):
    _env(monkeypatch, typesafe="ts", transport="typesafe")
    sent = _install(monkeypatch)
    run_judge("edit-fidelity", _STATE)
    assert sent[0].full_url == "https://api.typesafe.ai/v1/systemone"
    assert sent[0].get_header("Authorization") == "Bearer ts"


def test_oversized_state_is_skipped(monkeypatch):
    _env(monkeypatch, openrouter="k")
    sent = _install(monkeypatch)
    big = {"before": "а" * 20_000, "after": "а" * 20_000}
    result = run_judge("edit-fidelity", big)
    assert result.status == "skipped"
    assert result.answers == {}
    assert sent == []
    small = {"before": "a" * 15_000, "after": "a" * 15_000}
    assert run_judge("edit-fidelity", small).status == "ok"


def test_missing_key_is_unavailable_and_cli_exits_zero(monkeypatch, tmp_path):
    _env(monkeypatch)
    assert run_judge("edit-fidelity", _STATE).status == "unavailable"
    out = tmp_path / "judges-pilot.json"
    assert main(["pilot", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["status"] == "unavailable"
    assert report["transport"] is None
    assert len(report["cases"]) == 18
    assert all(case["status"] == "unavailable" for case in report["cases"])


def test_pilot_writes_report_of_expected_shape(monkeypatch, tmp_path):
    _env(monkeypatch, openrouter="k")
    sent = _install(monkeypatch)
    out = tmp_path / "judges-pilot.json"
    assert main(["pilot", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    report = json.loads(text)
    assert set(report) == {"version", "transport", "status", "cases", "usage"}
    assert report["transport"] == "openrouter"
    assert report["status"] == "ok"
    assert report["usage"] == {"input_tokens": 18 * 612}
    assert len(report["cases"]) == 18
    for case in report["cases"]:
        assert set(case) == {"id", "expect", "answers", "status", "elapsed_ms"}
    assert {case["expect"] for case in report["cases"]} == {"damage", "clean"}
    assert len(sent) == 18  # both questions of a pair travel in one request
    for request in sent:
        payload = json.loads(request.data)
        assert set(payload["state"]) == {"before", "after"}
        assert len(payload["questions"]) == 2
    # privacy: the report carries no pair texts
    assert "Препарат" not in text
    assert "резекци" not in text


def test_unknown_judge_id_raises(monkeypatch):
    _env(monkeypatch, openrouter="k")
    with pytest.raises(ValueError):
        run_judge("claim-support", _STATE)
