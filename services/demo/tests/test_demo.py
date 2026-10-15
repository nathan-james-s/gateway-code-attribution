"""T056-T058: demo-model speaks all four formats; the scripted sessions exercise every outcome."""

from __future__ import annotations

import http.client
import json
import shutil
import threading
from collections import Counter
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from gca_demo import agent, model
from gca_demo.sessions import demo_sessions, marker, sessions, tool_calls
from gca_demo.streams import render
from gca_prcheck.diff import added_from_blobs
from gcattr import (
    ALG,
    AddedLine,
    Candidate,
    CapturedToolOutput,
    FingerprintKey,
    attribute,
    extract,
    parse_stream,
)

KEY = FingerprintKey(1, b"\x24" * 32)


@pytest.mark.parametrize("stream", [True, False])
def test_every_step_round_trips(stream: bool) -> None:
    for s in sessions().values():
        for i, step in enumerate(s.steps):
            calls = tool_calls(step, f"c{i}")
            _, body = render(step.format, calls, stream=stream)
            outs = [o for o in parse_stream(step.format, [body]) if getattr(o, "kind", "") != "text_block"]  # type: ignore[arg-type]
            assert len(outs) == 1 and isinstance(outs[0], CapturedToolOutput) and outs[0].complete
            got = outs[0].payload
            if calls[0].freeform is not None:
                assert got == calls[0].freeform
            else:
                assert got == calls[0].args


def test_model_server_streams_in_small_chunks() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), model.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        body = json.dumps(
            {
                "model": "demo",
                "stream": True,
                "max_tokens": 10,
                "messages": [{"role": "user", "content": marker("pricing", 0)}],
            }
        )
        conn.request("POST", "/v1/messages", body, {"content-type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200 and resp.getheader("transfer-encoding") == "chunked"
        outs = list(parse_stream("anthropic_messages", [resp.read()]))
        assert any(getattr(o, "tool_name", None) == "Write" for o in outs)
        conn.request(
            "POST", "/v1beta/models/demo-gemini:streamGenerateContent?alt=sse", json.dumps({"contents": []})
        )
        resp = conn.getresponse()
        assert resp.status == 200 and b"data: " in resp.read()
    finally:
        server.shutdown()


def _send(api_format: str, text: str) -> bytes:
    path = {"gemini_native": "/v1beta/models/demo-gemini:streamGenerateContent"}.get(api_format, "/v1/x")
    body = json.dumps({"stream": True, "messages": [{"role": "user", "content": text}], "input": text})
    return model.respond(api_format, path, body)[1]


def test_demo_exercises_every_outcome(tmp_path: Path) -> None:
    base = agent.sample_repo_dir()
    repo = tmp_path / "repo"
    shutil.copytree(base, repo, ignore=shutil.ignore_patterns("__pycache__", ".*_cache"))
    outputs = agent.play(repo, demo_sessions().values(), _send)
    agent.format_python(repo)

    # Capture side: what the gateway would have fingerprinted.
    cands = [
        Candidate(
            f"ev{i}",
            fp.exact_fp,
            fp.minhash,
            fp.path_suffix_fps,
            fp.tool_call_ordinal,
            fp.line_ordinal,
            fp.alg,
            fp.key_gen,
            fp.lsh_bands,
        )
        for i, out in enumerate(outputs)
        for fp in extract(out, KEY, ALG, tool_call_ordinal=1)
    ]
    # PR side: added lines versus the sample project, all by one author.
    lines: list[AddedLine] = []
    for path in sorted(p for p in repo.rglob("*") if p.is_file()):
        rel = path.relative_to(repo).as_posix()
        old = (base / rel).read_text() if (base / rel).exists() else None
        lines += [AddedLine(rel, n, t, 1) for n, t in added_from_blobs(old, path.read_text())]
    results = attribute(lines, {1: cands}, {1: KEY}, ALG)
    by_line = {(ln.file_path, ln.text.strip()): r for ln, r in zip(lines, results, strict=True)}
    kinds = Counter(f"{r.outcome}:{r.tier}" for r in results)
    assert {
        "ai_unmodified:exact",
        "ai_modified:anchored",
        "ai_modified:broad",
        "human:none",
        "indeterminate:none",
    } <= set(kinds), kinds

    def outcome(path: str, prefix: str) -> str:
        hits = [
            f"{r.outcome}:{r.tier}" for (p, t), r in by_line.items() if p == path and t.startswith(prefix)
        ]
        assert len(hits) == 1, (path, prefix, hits)
        return hits[0]

    assert outcome("src/shop/inventory.py", "def reserve") == "ai_unmodified:exact"
    assert outcome("web/src/discount.ts", "export function bulkDiscountCents") == "ai_unmodified:exact"
    assert outcome("src/shop/receipt.py", "def render_receipt") == "ai_unmodified:exact"
    assert outcome("src/shop/pricing.py", "total = sum(") == "ai_modified:anchored"
    assert outcome("src/shop/alerts.py", "skus = sorted(") == "ai_modified:broad"
    assert outcome("src/shop/alerts.py", 'return [f"Low stock') == "human:none"
    assert outcome("src/shop/pricing.py", "def describe_discount") == "human:none"
    assert outcome("src/shop/pricing.py", "return total") == "indeterminate:none"


def test_apply_patch_update(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")
    patch = "*** Begin Patch\n*** Update File: a.py\n@@\n-y = 2\n+y = 3\n+z = 4\n*** End Patch\n"
    agent.apply_output(
        tmp_path, CapturedToolOutput("openai_responses", "apply_patch", "freeform", patch, True)
    )
    assert (tmp_path / "a.py").read_text() == "x = 1\ny = 3\nz = 4\n"


def test_refuses_paths_outside_repo(tmp_path: Path) -> None:
    out = CapturedToolOutput(
        "openai_chat", "write", "json_args", {"path": "../evil.py", "content": "x"}, True
    )
    with pytest.raises(agent.DemoError):
        agent.apply_output(tmp_path, out)


def test_inject_faults_sends_broken_responses_that_capture_counts() -> None:
    """T092: each injected fault reaches demo-model by its own API format and parses as that loss cause."""
    from gca_demo.sessions import FAULTS
    from gcattr import CaptureFailure, parse_stream

    assert agent.parse_faults("truncated=2, unexpected_format=1") == {"truncated": 2, "unexpected_format": 1}
    for bad in ("truncated", "slow=3", "truncated=x"):
        with pytest.raises(agent.DemoError):
            agent.parse_faults(bad)
    seen: Counter[str] = Counter()

    def send(api_format: str, text: str) -> bytes:
        path = "/v1/messages" if api_format == "anthropic_messages" else "/v1/responses"
        body = json.dumps({"stream": True, "messages": [{"role": "user", "content": text}]})
        data = model.respond(api_format, path, body)[1]
        for r in parse_stream(api_format, [data]):  # type: ignore[arg-type]
            if isinstance(r, CaptureFailure):
                seen[r.cause] += 1
        return data

    agent.inject_faults({"truncated": 3, "unexpected_format": 2}, send)
    assert seen == Counter({"truncated": 3, "unexpected_format": 2})
    # A fault marker sent to the other format gets an ordinary reply.
    assert FAULTS["truncated"] == "anthropic_messages"
    other = model.respond(
        "openai_chat", "/v1/chat/completions", '{"stream": true, "x": "gca-demo fault=truncated n=0"}'
    )
    assert b"max_tokens" not in other[1]
