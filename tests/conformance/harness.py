"""Cross-gateway conformance harness (T063; FR-006; research R4).

Runs the real gateways side by side against one upstream:
- agentgateway 1.6.0 (the release binary, checksum-verified) with our ext_proc capture server in-process;
- LiteLLM 1.105.1 (`uv run --with litellm[proxy]==1.105.1`) with our capture handler. The proxy runs as a
  subprocess because it keeps process-global state; a thin callback wraps the real handler and writes what it
  would publish to a file instead of NATS;
- demo-model as the upstream, extended here to also serve the assessment probe's fixture streams.

Both capture paths publish into in-memory collectors; requests are replayed one at a time so each request's
messages can be compared directly.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import grpc
import yaml
from envoy.service.ext_proc.v3 import external_processor_pb2_grpc as pbg

from gca_capture_extproc import worker
from gca_capture_extproc.lag import LagMonitor
from gca_capture_extproc.server import CaptureProcessor, make_executor
from gca_core.capture_runtime import CaptureRuntime
from gca_demo import model
from gca_demo.agent import gateway_sender

ROOT = Path(__file__).resolve().parents[2]
SECRET = b"\x5a" * 32
AG_KEY = "sk-gca-conformance-agentgateway-key"
LL_MASTER = "sk-conformance-master"
CRED_ID = "11111111-2222-3333-4444-555555555555"
LITELLM = "litellm[proxy]==1.105.1"
CHUNK = 7

_spec = importlib.util.spec_from_file_location("probe_fixtures", ROOT / "lib/tests/fixtures/streams.py")
fixtures = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(fixtures)  # type: ignore[union-attr]
_FIXTURE = re.compile(r"gca-fixture=([a-z_]+)")
FIXTURE_FORMATS = {
    "openai_chat": "openai_chat",
    "openai_responses": "openai_responses",
    "anthropic": "anthropic_messages",
    "anthropic_truncated": "anthropic_messages",
    "gemini": "gemini_native",
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_port(port: int, timeout: float, proc: subprocess.Popen[bytes] | None = None) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"process exited ({proc.returncode}) before port {port} opened")
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise TimeoutError(f"port {port} did not open")


def write_keys(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "1").write_text(base64.b64encode(SECRET).decode())
    (directory / "active").write_text("1")
    return directory


# ---------------------------------------------------------------------------------------------- upstream
class _Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: object) -> None:
        return

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("content-length") or 0)).decode("utf-8", "replace")
        api_format = model.route(self.path)
        if api_format is None:
            self.send_response(404)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        m = _FIXTURE.search(body)
        name = m.group(1) if m and m.group(1) in FIXTURE_FORMATS else None
        if name is not None:
            data = fixtures.FIXTURES[name]()[0].encode("utf-8")
        else:
            data = model.respond(api_format, self.path, body)[1]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        for i in range(0, len(data), CHUNK):  # split SSE lines and UTF-8 sequences, as the probe did
            c = data[i : i + CHUNK]
            self.wfile.write(b"%x\r\n%s\r\n" % (len(c), c))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


class Upstream:
    def __init__(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()


# ---------------------------------------------------------------------------------------------- agentgateway
def agentgateway_binary() -> Path:
    if os.environ.get("GCA_AGENTGATEWAY_BIN"):
        return Path(os.environ["GCA_AGENTGATEWAY_BIN"])
    pins = yaml.safe_load((ROOT / "versions.yaml").read_text())["binaries"]["agentgateway"]
    os_name = {"Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "amd64", "AMD64": "amd64"}[platform.machine()]
    want = pins["sha256"].get(f"{os_name}-{arch}")
    if not want:
        raise RuntimeError(f"no pinned agentgateway checksum for {os_name}-{arch} in versions.yaml")
    path = Path.home() / ".cache/gca" / f"agentgateway-{pins['version']}-{os_name}-{arch}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        url = pins["url"].format(os=os_name, arch=arch)
        with urllib.request.urlopen(url, timeout=300) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != want:
            raise RuntimeError(f"checksum mismatch for {url}")
        path.write_bytes(data)
        path.chmod(0o755)
    if hashlib.sha256(path.read_bytes()).hexdigest() != want:
        raise RuntimeError(f"cached {path} does not match its pinned checksum")
    return path


class ExtProc:
    """Our capture server on a background event loop; published messages land in ``messages``."""

    def __init__(self, keys_dir: Path) -> None:
        self.port = free_port()
        self.messages: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()
        self.keys_dir = keys_dir
        threading.Thread(target=self._run, daemon=True).start()
        if not self.ready.wait(60):
            raise TimeoutError("ext_proc server did not start")

    async def _send(self, subject: str, payload: bytes) -> None:
        with self.lock:
            self.messages.append(json.loads(payload))

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._start())
        self.ready.set()
        self.loop.run_forever()

    async def _start(self) -> None:
        def factory() -> Any:
            return make_executor(1, str(self.keys_dir))

        executor = factory()
        await asyncio.get_running_loop().run_in_executor(executor, worker.ping)
        self.runtime = CaptureRuntime("agentgateway", self._send, heartbeat_seconds=3600)
        processor = CaptureProcessor(self.runtime, executor, LagMonitor(), executor_factory=factory)
        self.server = grpc.aio.server()
        pbg.add_ExternalProcessorServicer_to_server(processor, self.server)
        self.server.add_insecure_port(f"127.0.0.1:{self.port}")
        await self.server.start()
        self.runtime.start()

    def stop(self) -> None:
        asyncio.run_coroutine_threadsafe(self.server.stop(None), self.loop).result(30)
        self.loop.call_soon_threadsafe(self.loop.stop)


def agentgateway_config(port: int, extproc_port: int, upstream: int) -> dict[str, Any]:
    base = f"http://127.0.0.1:{upstream}"
    return {
        "llm": {
            "port": port,
            "policies": {
                "apiKey": {
                    "mode": "strict",
                    "location": {
                        "expression": (
                            'default(request.headers["x-api-key"], default(request.headers["x-goog-api-key"], '
                            'request.headers["authorization"].regexReplace("^Bearer ", "")))'
                        )
                    },
                    "keys": [
                        {
                            "keyHash": "sha256:" + hashlib.sha256(AG_KEY.encode()).hexdigest(),
                            "metadata": {"credential_id": CRED_ID, "github_id": 4242},
                        }
                    ],
                },
                "extProc": {
                    "host": f"127.0.0.1:{extproc_port}",
                    "failureMode": "failOpen",
                    "processingOptions": {
                        "requestHeaderMode": "send",
                        "responseHeaderMode": "send",
                        "requestBodyMode": "none",
                        "responseBodyMode": "fullDuplexStreamed",
                    },
                    "metadataContext": {
                        "gca": {
                            "credential_id": "apiKey.credential_id",
                            "github_id": "apiKey.github_id",
                            "path": "request.path",
                        }
                    },
                },
            },
            "models": [
                {
                    "name": "demo-openai",
                    "provider": "openAI",
                    "params": {"model": "demo", "baseUrl": f"{base}/v1", "apiKey": "demo"},
                },
                {
                    "name": "demo-anthropic",
                    "provider": "anthropic",
                    "params": {"model": "demo", "baseUrl": f"{base}/v1", "apiKey": "demo"},
                },
                {
                    "name": "demo-gemini",
                    "provider": "gemini",
                    "params": {"model": "demo-gemini", "baseUrl": f"{base}/v1beta", "apiKey": "demo"},
                },
            ],
        }
    }


# ---------------------------------------------------------------------------------------------- litellm
CALLBACK = '''
"""Conformance callback: the real capture handler, publishing to a file instead of NATS."""
import json, os
from gca_capture_litellm import handler as h

_meta = h._metadata


def _metadata(kwargs):  # no LiteLLM database here, so no key alias: stand in a fixed credential
    return {**_meta(kwargs), "user_api_key_alias": "conformance"}


h._metadata = _metadata


class Conformance(h.GcaHandler):
    async def _send(self, subject, payload):
        with open(os.environ["GCA_CONFORMANCE_OUT"], "ab") as fh:
            fh.write(payload + b"\\n")


handler = Conformance()
'''


def litellm_config(upstream: int) -> dict[str, Any]:
    base = f"http://127.0.0.1:{upstream}"
    return {
        "model_list": [
            {
                "model_name": "demo-openai",
                "litellm_params": {"model": "openai/demo", "api_base": f"{base}/v1", "api_key": "demo"},
            },
            {
                "model_name": "demo-anthropic",
                "litellm_params": {"model": "anthropic/demo", "api_base": base, "api_key": "demo"},
            },
            {
                "model_name": "demo-gemini",
                "litellm_params": {"model": "gemini/demo-gemini", "api_base": base, "api_key": "demo"},
            },
        ],
        "litellm_settings": {"callbacks": ["conformance_callback.handler"]},
        "general_settings": {"master_key": LL_MASTER},
    }


class Proc:
    def __init__(self, cmd: list[str], env: dict[str, str], log: Path) -> None:
        self.log = log
        self.fh = log.open("wb")
        self.proc = subprocess.Popen(
            cmd, cwd=ROOT, env={**os.environ, **env}, stdout=self.fh, stderr=subprocess.STDOUT
        )

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.fh.close()


class FileCollector:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.write_bytes(b"")

    @property
    def messages(self) -> list[dict[str, Any]]:
        return [json.loads(ln) for ln in self.path.read_bytes().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------------------------- comparison
def canonical(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """What a request produced, independent of ordering and transport: per event the multiset of
    (t, l, x, m, b, p), plus the loss causes reported."""
    events = []
    for m in messages:
        if m.get("kind") == "event":
            lines = sorted(
                json.dumps([ln["t"], ln["l"], ln["x"], ln["m"], ln["b"], ln.get("p", [])])
                for ln in m["lines"]
            )
            events.append({"api_format": m["api_format"], "status": m["status"], "lines": lines})
    failures = sorted(m["cause"] for m in messages if m.get("kind") == "failure")
    return {"events": sorted(events, key=lambda e: json.dumps(e)), "failures": failures}


def replay(
    send: Callable[[str, str], bytes],
    messages: Callable[[], list[dict[str, Any]]],
    api_format: str,
    text: str,
    settle: float = 1.5,
    timeout: float = 30,
) -> dict[str, Any]:
    """Send one request; return the canonical messages it produced (heartbeats excluded)."""
    before = len(messages())
    send(api_format, text)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        new = [m for m in messages()[before:] if m.get("kind") in ("event", "failure")]
        if new:
            time.sleep(settle)  # let any trailing loss records for the same response arrive
            return canonical([m for m in messages()[before:] if m.get("kind") in ("event", "failure")])
        time.sleep(0.1)
    return canonical([])


def sender(base_url: str, credential: str, gateway: str) -> Callable[[str, str], bytes]:
    return gateway_sender(base_url, credential, gateway)


def python() -> str:
    return sys.executable
