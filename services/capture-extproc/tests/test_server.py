"""T040-T042: ext_proc stubs, pass-through echo and capture, using the assessment probe's fixture streams."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
from concurrent.futures import Executor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import grpc
import pytest
from envoy.config.core.v3 import base_pb2
from envoy.service.ext_proc.v3 import external_processor_pb2 as pb
from envoy.service.ext_proc.v3 import external_processor_pb2_grpc as pbg
from google.protobuf import struct_pb2

from gca_capture_extproc import worker
from gca_capture_extproc.api_format import api_format_for_path, tool_hint
from gca_capture_extproc.lag import LagMonitor
from gca_capture_extproc.server import CaptureProcessor, health_server, make_executor
from gca_core.capture_runtime import CaptureRuntime
from gcattr import ALG, FingerprintKey, extract, parse_stream

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("fx", ROOT / "lib/tests/fixtures/streams.py")
fx = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(fx)  # type: ignore[union-attr]
SECRET = b"\x42" * 32


@pytest.fixture
def keys_dir(tmp_path: Path) -> str:
    (tmp_path / "1").write_text(base64.b64encode(SECRET).decode())
    (tmp_path / "active").write_text("1")
    return str(tmp_path)


def test_stub_import() -> None:
    assert hasattr(pb, "StreamedBodyResponse") and hasattr(pbg, "ExternalProcessorServicer")


@pytest.mark.parametrize(
    ("path", "fmt"),
    [
        ("/v1/chat/completions", "openai_chat"),
        ("/v1/responses?x=1", "openai_responses"),
        ("/v1/messages", "anthropic_messages"),
        ("/v1beta/models/g:streamGenerateContent?alt=sse", "gemini_native"),
        ("/v1/models", None),
        (None, None),
    ],
)
def test_api_format(path: str | None, fmt: str | None) -> None:
    assert api_format_for_path(path) == fmt


def test_tool_hint() -> None:
    assert tool_hint({"x-claude-code-session-id": "s"}) == "claude-code"
    assert tool_hint({"user-agent": "codex_cli_rs/0.40"}) == "codex-cli"
    assert tool_hint({"user-agent": "curl/8"}) is None


def _requests(path: str, data: bytes, chunk: int, meta: dict) -> list[pb.ProcessingRequest]:
    def hm(pairs: dict[str, str]) -> base_pb2.HeaderMap:
        return base_pb2.HeaderMap(
            headers=[base_pb2.HeaderValue(key=k, raw_value=v.encode()) for k, v in pairs.items()]
        )

    md = struct_pb2.Struct()
    md.update(meta)
    ctx = base_pb2.Metadata(filter_metadata={"gca": md}) if meta else None
    out = [
        pb.ProcessingRequest(
            request_headers=pb.HttpHeaders(headers=hm({":path": path, "user-agent": "claude-cli/2"})),
            metadata_context=ctx,
        )
    ]
    out.append(pb.ProcessingRequest(response_headers=pb.HttpHeaders(headers=hm({":status": "200"}))))
    parts = [data[i : i + chunk] for i in range(0, len(data), chunk)]
    for i, p in enumerate(parts):
        out.append(pb.ProcessingRequest(response_body=pb.HttpBody(body=p, end_of_stream=i == len(parts) - 1)))
    return out


async def _run(
    keys_dir: str, path: str, data: bytes, meta: dict, chunk: int = 7, executor: Executor | None = None
) -> tuple[bytes, list[dict]]:
    sent: list[dict] = []

    async def send(subject: str, payload: bytes) -> None:
        sent.append(json.loads(payload))

    runtime = CaptureRuntime("agentgateway", send, heartbeat_seconds=60)
    worker.init(keys_dir)
    lag = LagMonitor()
    proc = CaptureProcessor(runtime, executor or ThreadPoolExecutor(1), lag)
    server = grpc.aio.server()
    pbg.add_ExternalProcessorServicer_to_server(proc, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    runtime.publisher.start()
    echoed = bytearray()
    async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as ch:
        stub = pbg.ExternalProcessorStub(ch)
        async for resp in stub.Process(iter(_requests(path, data, chunk, meta))):
            if resp.WhichOneof("response") == "response_body":
                echoed += resp.response_body.response.body_mutation.streamed_response.body
    for _ in range(500):
        await asyncio.sleep(0.02)
        if sent:
            break
    await asyncio.sleep(0.05)
    await runtime.publisher.stop()
    await server.stop(None)
    return bytes(echoed), sent


@pytest.mark.parametrize(
    ("name", "path", "fmt"),
    [
        ("openai_chat", "/v1/chat/completions", "openai_chat"),
        ("openai_responses", "/v1/responses", "openai_responses"),
        ("anthropic", "/v1/messages", "anthropic_messages"),
        ("gemini", "/v1beta/models/m:streamGenerateContent?alt=sse", "gemini_native"),
    ],
)
async def test_echo_is_identical_and_fingerprints_match_library(
    keys_dir: str, name: str, path: str, fmt: str
) -> None:
    data = fx.FIXTURES[name]()[0].encode()
    echoed, sent = await _run(keys_dir, path, data, {"credential_id": "c-1", "github_id": 4242})
    assert echoed == data
    events = [m for m in sent if m["kind"] == "event"]
    assert len(events) == 1 and events[0]["status"] == "captured" and events[0]["credential_id"] == "c-1"
    assert events[0]["tool_hint"] == "claude-code" and events[0]["model"] in ("mock", "m")
    key = FingerprintKey(1, SECRET)
    expected = []
    for i, o in enumerate(
        (r for r in parse_stream(fmt, [data]) if getattr(r, "kind", "") != "text_block"), 1
    ):
        expected.extend(extract(o, key, ALG, tool_call_ordinal=i))
    got = sorted((ln["t"], ln["l"], ln["x"]) for ln in events[0]["lines"])
    assert got == sorted(
        (f.tool_call_ordinal, f.line_ordinal, base64.b64encode(f.exact_fp).decode()) for f in expected
    )


async def test_truncated_stream_is_partial_with_loss(keys_dir: str) -> None:
    data = fx.FIXTURES["anthropic_truncated"]()[0].encode()
    echoed, sent = await _run(keys_dir, "/v1/messages", data, {"credential_id": "c-1"})
    assert echoed == data
    kinds = [(m["kind"], m.get("status"), m.get("cause")) for m in sent]
    assert ("event", "partial", None) in kinds and ("failure", None, "truncated") in kinds


async def test_missing_identity_counts_unknown_credential(keys_dir: str) -> None:
    data = fx.FIXTURES["openai_chat"]()[0].encode()
    echoed, sent = await _run(keys_dir, "/v1/chat/completions", data, {})
    assert echoed == data
    assert [(m["kind"], m.get("cause")) for m in sent] == [("failure", "unknown_credential")]


async def test_no_content_in_published_messages(keys_dir: str) -> None:
    data = fx.FIXTURES["openai_chat"]()[0].encode()
    _, sent = await _run(keys_dir, "/v1/chat/completions", data, {"credential_id": "c-1"})
    blob = json.dumps(sent)
    for needle in ("def total", "subtotal", "round(", "café"):
        assert needle not in blob


async def test_real_process_pool_with_grpc_running(keys_dir: str) -> None:
    """Regression: a fork()ed pool crashed inside gRPC on the first request (first kind install)."""
    pool = make_executor(2, keys_dir)
    try:
        await asyncio.get_running_loop().run_in_executor(pool, worker.ping)  # warm before gRPC starts
        data, _ = fx.FIXTURES["anthropic"]()
        for _ in range(2):
            _, sent = await _run(
                keys_dir, "/v1/messages", data.encode(), {"credential_id": "c-1"}, executor=pool
            )
            assert [m["kind"] for m in sent] == ["event"] and sent[0]["lines"]
    finally:
        pool.shutdown()


class _BrokenOnce(ThreadPoolExecutor):
    def submit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise BrokenProcessPool("worker died")


async def test_broken_pool_is_replaced_and_counted(keys_dir: str) -> None:
    sent: list[dict] = []

    async def send(subject: str, payload: bytes) -> None:
        sent.append(json.loads(payload))

    worker.init(keys_dir)
    runtime = CaptureRuntime("agentgateway", send, heartbeat_seconds=60)
    proc = CaptureProcessor(
        runtime, _BrokenOnce(1), LagMonitor(), executor_factory=lambda: ThreadPoolExecutor(1)
    )
    data, _ = fx.FIXTURES["openai_chat"]()
    await proc._fingerprint_and_emit("openai_chat", data.encode(), "c-1", None, None)
    assert proc.pool_restarts == 1 and isinstance(proc.executor, ThreadPoolExecutor)
    await proc._fingerprint_and_emit("openai_chat", data.encode(), "c-1", None, None)
    runtime.publisher.start()
    await runtime.publisher.drain()
    await runtime.publisher.stop()
    assert [(m["kind"], m.get("cause")) for m in sent] == [("failure", "unparsable"), ("event", None)]


async def test_health_endpoint(keys_dir: str) -> None:
    runtime = CaptureRuntime("agentgateway", lambda s, p: asyncio.sleep(0), heartbeat_seconds=60)
    proc = CaptureProcessor(runtime, ThreadPoolExecutor(1), LagMonitor())
    server = await health_server(proc, 0)
    port = server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET /healthz HTTP/1.1\r\n\r\n")
    await writer.drain()
    assert (await reader.read()).startswith(b"HTTP/1.1 200 OK")
    server.close()
