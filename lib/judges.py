"""Decision-model judges (Jev): typed questions over a small before/after state.

A judge asks the fixed questions of its descriptor (`canon/judges.json`) about one
state fragment and returns per-question probabilities. The transport (OpenRouter
Decisions or TypeSafe systemone) is picked by `SW_JUDGE__TRANSPORT`, or by whichever
API key is present in the environment. Keys travel in the request header only —
never into logs, reports or exceptions. A state above ~32 000 bytes is skipped:
larger fragments fall into the less accurate long-context mode. Statuses:
ok | refused | skipped | unavailable | error.
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CANON = _REPO / "canon" / "judges.json"

_MODEL = "typesafe/jev-1.14"
_MAX_STATE_BYTES = 32_000
_TIMEOUT_S = 60
# url + name of the environment variable holding the key
_TRANSPORTS = {
    "openrouter": ("https://openrouter.ai/api/alpha/decisions", "OPENROUTER_API_KEY"),
    "typesafe": ("https://api.typesafe.ai/v1/systemone", "TYPESAFE_API_KEY"),
}


@dataclass(frozen=True, slots=True)
class JudgeResult:
    status: str  # ok | refused | skipped | unavailable | error
    answers: dict[str, float]
    usage: dict[str, int]
    elapsed_ms: int


def _judges() -> dict[str, dict[str, object]]:
    return json.loads(_CANON.read_text(encoding="utf-8"))["judges"]


def _resolve_transport() -> tuple[str, str] | None:
    explicit = os.environ.get("SW_JUDGE__TRANSPORT", "")
    if explicit:
        entry = _TRANSPORTS.get(explicit)
        key = os.environ.get(entry[1], "") if entry else ""
        return (explicit, key) if entry and key else None
    for name, (_url, var) in _TRANSPORTS.items():
        key = os.environ.get(var, "")
        if key:
            return name, key
    return None


def _state_bytes(state: dict[str, str]) -> int:
    return len(json.dumps(state, ensure_ascii=False).encode("utf-8"))


def run_judge(judge_id: str, state: dict[str, str]) -> JudgeResult:
    started = time.monotonic()

    def done(status: str, answers: dict[str, float] | None = None,
             usage: dict[str, int] | None = None) -> JudgeResult:
        return JudgeResult(status, answers or {}, usage or {},
                           int((time.monotonic() - started) * 1000))

    desc = _judges().get(judge_id)
    if desc is None:
        raise ValueError(f"unknown judge id: {judge_id}")
    if set(state) != set(desc["state"]):
        raise ValueError(f"state keys must be exactly {sorted(desc['state'])}")
    transport = _resolve_transport()
    if transport is None:
        return done("unavailable")
    if _state_bytes(state) > _MAX_STATE_BYTES:
        return done("skipped")
    name, api_key = transport
    url, _var = _TRANSPORTS[name]
    questions = {qname: {"type": q["type"], "question": q["question"]}
                 for qname, q in desc["questions"].items()}
    request = urllib.request.Request(
        url,
        data=json.dumps({"model": _MODEL, "state": state, "questions": questions},
                        ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            body = response.read()
    except OSError:
        # network failures and HTTPError (incl. 5xx) are OSError subclasses
        return done("error")
    try:
        data = json.loads(body)
        raw = data["answers"]
        usage_raw = data.get("usage", {})
    except (json.JSONDecodeError, KeyError, TypeError):
        return done("error")
    answers: dict[str, float] = {}
    refused = False
    for qname in questions:
        entry = raw.get(qname) if isinstance(raw, dict) else None
        if not isinstance(entry, dict):
            return done("error")
        kind = entry.get("type")
        if kind == "refusal":
            refused = True
            continue
        value = entry.get("value")
        if (kind != "noul" or not isinstance(value, (int, float))
                or isinstance(value, bool)):
            return done("error")
        answers[qname] = float(value)
    tokens = usage_raw.get("input_tokens") if isinstance(usage_raw, dict) else None
    usage = {"input_tokens": tokens} if isinstance(tokens, int) else {}
    return done("refused" if refused else "ok", answers, usage)
