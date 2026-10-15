"""T044: the LiteLLM handler publishes fingerprints matching the library, and counts failures."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest

from gca_capture_litellm.handler import GcaHandler
from gca_core.capture_runtime import CaptureRuntime
from gcattr import ALG, FingerprintKey, extract, from_litellm

SECRET = b"\x42" * 32
CODE = "def total(items):\n    subtotal = sum(i.price for i in items)\n    return round(subtotal, 2)\n"


@pytest.fixture
def handler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    (tmp_path / "1").write_text(base64.b64encode(SECRET).decode())
    (tmp_path / "active").write_text("1")
    monkeypatch.setenv("GCA_KEYS_DIR", str(tmp_path))
    h = GcaHandler()
    sent: list[dict] = []

    async def send(subject: str, payload: bytes) -> None:
        sent.append(json.loads(payload))

    h._runtime = CaptureRuntime("litellm", send, heartbeat_seconds=60)
    h.sent = sent  # type: ignore[attr-defined]
    return h


def _chat(args: str, finish: str = "tool_calls") -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {
                    "content": "ok",
                    "tool_calls": [
                        {"id": "c1", "type": "function", "function": {"name": "Write", "arguments": args}}
                    ],
                },
            }
        ]
    }


def _kwargs(call_type: str = "acompletion", alias: str | None = "cred-1") -> dict:
    md = {"user_api_key_user_id": "4242", "model_group": "demo-openai"}
    if alias:
        md["user_api_key_alias"] = alias
    return {"call_type": call_type, "model": "demo", "litellm_params": {"metadata": md}}


async def _flush(h: GcaHandler) -> list[dict]:
    rt = h._runtime
    rt.publisher.start()
    await rt.publisher.drain()
    await rt.publisher.stop()
    return h.sent  # type: ignore[attr-defined,no-any-return]


async def test_success_event_matches_library(handler: GcaHandler) -> None:
    resp = _chat(json.dumps({"file_path": "/r/src/app.py", "content": CODE}))
    await handler.async_log_success_event(_kwargs(), resp, None, None)
    sent = await _flush(handler)
    ev = next(m for m in sent if m["kind"] == "event")
    assert ev["credential_id"] == "cred-1" and ev["model"] == "demo-openai" and ev["status"] == "captured"
    key = FingerprintKey(1, SECRET)
    out = next(o for o in from_litellm(resp, "acompletion") if getattr(o, "kind", "") != "text_block")
    assert sorted(ln["x"] for ln in ev["lines"]) == sorted(
        base64.b64encode(f.exact_fp).decode() for f in extract(out, key, ALG, tool_call_ordinal=1)
    )
    assert "subtotal" not in json.dumps(sent)


async def test_truncated_args_partial_plus_loss(handler: GcaHandler) -> None:
    resp = _chat(
        '{"file_path": "/r/a.py", "content": "alpha = make(1)\\nbeta = make(2)\\ngam', finish="length"
    )
    await handler.async_log_success_event(_kwargs(), resp, None, None)
    kinds = [(m["kind"], m.get("status"), m.get("cause")) for m in await _flush(handler)]
    assert ("event", "partial", None) in kinds and ("failure", None, "truncated") in kinds


async def test_unknown_credential_and_non_code_calls(handler: GcaHandler) -> None:
    await handler.async_log_success_event(_kwargs(alias=None), _chat("{}"), None, None)
    await handler.async_log_success_event(_kwargs(call_type="aembedding"), {"data": []}, None, None)
    sent = await _flush(handler)
    assert [(m["kind"], m.get("cause")) for m in sent] == [("failure", "unknown_credential")]


async def test_never_raises_on_garbage(handler: GcaHandler) -> None:
    await handler.async_log_success_event(_kwargs(), object(), None, None)
    sent = await _flush(handler)
    assert sent and all(m["kind"] == "failure" for m in sent)


async def test_responses_freeform_patch(handler: GcaHandler) -> None:
    resp = {
        "status": "completed",
        "output": [
            {
                "type": "custom_tool_call",
                "name": "apply_patch",
                "call_id": "c",
                "input": "*** Begin Patch\n*** Update File: src/a.py\n+value = compute(a, b)\n*** End Patch\n",
            }
        ],
    }
    await handler.async_log_success_event(_kwargs(call_type="aresponses"), resp, None, None)
    ev = next(m for m in await _flush(handler) if m["kind"] == "event")
    assert ev["api_format"] == "openai_responses" and len(ev["lines"]) == 1 and ev["lines"][0]["p"]


def test_module_level_handler_exists() -> None:
    from gca_capture_litellm import handler as mod

    assert isinstance(mod.handler, GcaHandler)
    asyncio.get_event_loop_policy()


async def test_gemini_generate_content_is_captured(handler: GcaHandler) -> None:
    resp = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "write_file",
                                "args": {
                                    "file_path": "src/a.py",
                                    "content": "value = compute(alpha, beta)\n",
                                },
                            }
                        }
                    ],
                },
                "finishReason": "STOP",
            }
        ]
    }
    await handler.async_log_success_event(_kwargs(call_type="agenerate_content_stream"), resp, None, None)
    ev = next(m for m in await _flush(handler) if m["kind"] == "event")
    assert ev["api_format"] == "gemini_native" and len(ev["lines"]) == 1


async def test_unrecognised_generative_call_is_counted_not_dropped(handler: GcaHandler) -> None:
    await handler.async_log_success_event(_kwargs(call_type="some_future_route"), {"x": 1}, None, None)
    sent = await _flush(handler)
    assert [(m["kind"], m.get("cause")) for m in sent] == [("failure", "unsupported_combination")]


async def test_tool_hint_from_request_headers(handler: GcaHandler) -> None:
    """T090: LiteLLM passes the client's headers to callbacks; capture records which tool sent the request."""
    kw = _kwargs()
    kw["litellm_params"]["metadata"]["headers"] = {"User-Agent": "codex_cli_rs/0.40", "session_id": "s-9"}
    resp = _chat(json.dumps({"file_path": "/r/src/app.py", "content": CODE}))
    await handler.async_log_success_event(kw, resp, None, None)
    kw = _kwargs(call_type="some_future_route")
    kw["litellm_params"]["proxy_server_request"] = {"headers": {"x-opencode-session-id": "o-1"}}
    await handler.async_log_success_event(kw, {"x": 1}, None, None)
    sent = await _flush(handler)
    ev = next(m for m in sent if m["kind"] == "event")
    assert ev["tool_hint"] == "codex-cli" and ev["session_id"] == "s-9"
    fail = next(m for m in sent if m["kind"] == "failure")
    assert (fail["cause"], fail["tool_hint"], fail["credential_id"]) == (
        "unsupported_combination",
        "opencode",
        "cred-1",
    )


async def test_unrecognised_call_without_credential_is_unknown_credential(handler: GcaHandler) -> None:
    await handler.async_log_success_event(
        _kwargs(call_type="some_future_route", alias=None), {"x": 1}, None, None
    )
    sent = await _flush(handler)
    assert [(m["kind"], m.get("cause")) for m in sent] == [("failure", "unknown_credential")]
