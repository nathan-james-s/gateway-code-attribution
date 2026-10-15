"""The real gateways, run locally side by side (T063, T106; FR-006; research R4).

- agentgateway 1.6.0 (the release binary, checksum-verified) with our ext_proc capture server in-process;
- LiteLLM 1.105.1 (`uv run --with litellm[proxy]==1.105.1`) with our capture handler, as a subprocess (it keeps
  process-global state). A thin callback wraps the real handler and writes what it would publish to a file;
- one upstream that answers every model request through a ``respond(api_format, path, body)`` function.

Each test developer has a gateway credential. On agentgateway that's a real key with the credential id in its
metadata, as the portal configures it. LiteLLM runs without its database, so the client names the credential in
an `x-gca-eval-credential` header and the callback uses it as the key alias the portal would have set.

Used by the conformance suite (tests/conformance) and the eval runner (gca_eval.runner).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

# gRPC logs a line on every fork (git, alembic) from this process; keep its log to errors. Set before importing it.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

import grpc
import yaml
from envoy.service.ext_proc.v3 import external_processor_pb2_grpc as pbg

from gca_capture_extproc import worker
from gca_capture_extproc.lag import LagMonitor
from gca_capture_extproc.server import CaptureProcessor, make_executor
from gca_core.capture_runtime import CaptureRuntime
from gca_demo import model
from gca_demo.agent import gateway_sender

__all__ = [
    "GATEWAYS",
    "LITELLM",
    "Credential",
    "Stack",
    "canonical",
    "free_port",
    "replay",
    "stack",
]

ROOT = Path(__file__).resolve().parents[4]
LITELLM = "litellm[proxy]==1.105.1"
LITELLM_MASTER = "sk-gca-eval-master"
CREDENTIAL_HEADER = "x-gca-eval-credential"
GATEWAYS = ("agentgateway", "litellm")
CHUNK = 7  # split SSE lines and UTF-8 sequences across writes, as the probe did

Respond = Callable[
    [str, str, str], bytes | None
]  # (api_format, path, body) -> stream, or None for the default


@dataclass(frozen=True)
class Credential:
    key: str  # the gateway key a developer's tool sends
    credential_id: str
    github_id: int


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


# ---------------------------------------------------------------------------------------------- upstream
class _Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    respond: Respond = staticmethod(lambda fmt, path, body: None)

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
        data = self.server.respond(api_format, self.path, body)  # type: ignore[attr-defined]
        if data is None:
            data = model.respond(api_format, self.path, body)[1]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        for i in range(0, len(data), CHUNK):
            c = data[i : i + CHUNK]
            self.wfile.write(b"%x\r\n%s\r\n" % (len(c), c))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


class Upstream:
    def __init__(self, respond: Respond) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
        self.server.respond = respond  # type: ignore[attr-defined]
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
        with urllib.request.urlopen(url, timeout=300) as r:  # noqa: S310 - pinned https URL
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

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.messages)

    def stop(self) -> None:
        asyncio.run_coroutine_threadsafe(self.server.stop(None), self.loop).result(30)
        self.loop.call_soon_threadsafe(self.loop.stop)


def agentgateway_config(
    port: int, extproc_port: int, upstream: int, credentials: list[Credential]
) -> dict[str, Any]:
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
                            "keyHash": "sha256:" + hashlib.sha256(c.key.encode()).hexdigest(),
                            "metadata": {"credential_id": c.credential_id, "github_id": c.github_id},
                        }
                        for c in credentials
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
"""The real capture handler, publishing to a file instead of NATS (gca_eval.gateways)."""
import json, os
from gca_capture_litellm import handler as h

_meta = h._metadata


def _metadata(kwargs):
    # No LiteLLM database here, so no key alias: take the credential the client named (x-gca-eval-credential).
    md = _meta(kwargs)
    headers = h._request_headers(kwargs, md)
    return {**md, "user_api_key_alias": headers.get("x-gca-eval-credential") or "conformance"}


h._metadata = _metadata


class Collected(h.GcaHandler):
    async def _send(self, subject, payload):
        with open(os.environ["GCA_CONFORMANCE_OUT"], "ab") as fh:
            fh.write(payload + b"\\n")


handler = Collected()
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
        "litellm_settings": {"callbacks": ["gca_eval_callback.handler"]},
        "general_settings": {"master_key": LITELLM_MASTER},
    }


class Proc:
    def __init__(self, cmd: list[str], env: dict[str, str], log: Path) -> None:
        self.log = log
        self.fh = log.open("wb")
        self.proc = subprocess.Popen(  # noqa: S603 - fixed commands
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
        path.touch()

    def snapshot(self) -> list[dict[str, Any]]:
        return [json.loads(ln) for ln in self.path.read_text().splitlines() if ln.strip()]


# ---------------------------------------------------------------------------------------------- the stack
@dataclass
class Stack:
    """Both gateways, ready to take requests. ``send(gateway, credential)`` returns a sender for a developer."""

    ports: dict[str, int]
    collectors: dict[str, Any]
    keys_dir: Path
    versions: dict[str, str] = field(default_factory=dict)

    def send(self, gateway: str, credential: Credential) -> Callable[[str, str], bytes]:
        base = f"http://127.0.0.1:{self.ports[gateway]}"
        if gateway == "agentgateway":
            return gateway_sender(base, credential.key, gateway)
        return gateway_sender(base, LITELLM_MASTER, gateway, {CREDENTIAL_HEADER: credential.credential_id})

    def messages(self, gateway: str) -> list[dict[str, Any]]:
        return list(self.collectors[gateway].snapshot())


@contextmanager
def stack(
    keys_dir: Path,
    credentials: list[Credential],
    respond: Respond,
    gateways: tuple[str, ...] = GATEWAYS,
) -> Iterator[Stack]:
    """Start the requested gateways in front of one upstream; stop everything afterwards."""
    if "litellm" in gateways and shutil.which("uv") is None:
        raise RuntimeError("uv is required to run the pinned LiteLLM")
    tmp = Path(tempfile.mkdtemp(prefix="gca-gateways-"))
    upstream = Upstream(respond)
    procs: list[Proc] = []
    collectors: dict[str, Any] = {}
    ports: dict[str, int] = {}
    extproc = None
    try:
        if "agentgateway" in gateways:
            extproc = ExtProc(keys_dir)
            ports["agentgateway"] = free_port()
            (tmp / "agentgateway.yaml").write_text(
                yaml.safe_dump(
                    agentgateway_config(ports["agentgateway"], extproc.port, upstream.port, credentials)
                )
            )
            ag = Proc(
                [str(agentgateway_binary()), "-f", str(tmp / "agentgateway.yaml")],
                {},
                tmp / "agentgateway.log",
            )
            procs.append(ag)
            collectors["agentgateway"] = extproc
            wait_port(ports["agentgateway"], 60, ag.proc)
        if "litellm" in gateways:
            ports["litellm"] = free_port()
            (tmp / "gca_eval_callback.py").write_text(CALLBACK)
            (tmp / "litellm.yaml").write_text(yaml.safe_dump(litellm_config(upstream.port)))
            out = FileCollector(tmp / "litellm-messages.jsonl")
            ll = Proc(
                ["uv", "run", "--quiet", "--with", LITELLM, "litellm", "--config", str(tmp / "litellm.yaml"),
                 "--port", str(ports["litellm"])],
                {"PYTHONPATH": str(tmp), "GCA_KEYS_DIR": str(keys_dir), "GCA_CONFORMANCE_OUT": str(out.path),
                 "LITELLM_LOG": "ERROR"},
                tmp / "litellm.log",
            )  # fmt: skip
            procs.append(ll)
            collectors["litellm"] = out
            wait_port(ports["litellm"], 900, ll.proc)  # the first run installs LiteLLM into uv's cache
        versions = {"agentgateway": "1.6.0", "litellm": LITELLM.split("==")[1]}
        yield Stack(ports, collectors, keys_dir, {g: versions[g] for g in gateways})
    finally:
        for p in procs:
            p.stop()
        if extproc is not None:
            extproc.stop()
        upstream.stop()
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------------------------- replaying
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


client_errors: list[str] = []  # requests the gateway failed, in order (read by the eval runner)


def replay(
    send: Callable[[str, str], bytes],
    messages: Callable[[], list[dict[str, Any]]],
    api_format: str,
    text: str,
    settle: float = 1.5,
    timeout: float = 30,
) -> list[dict[str, Any]]:
    """Send one request; return the event and failure messages it produced (heartbeats excluded). A request the
    gateway fails (the client sees an error or a cut-off body) still returns whatever capture reported for it."""
    before = len(messages())
    try:
        send(api_format, text)
    except Exception as exc:
        client_errors.append(f"{api_format}: {type(exc).__name__}: {str(exc)[:120]}")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        new = [m for m in messages()[before:] if m.get("kind") in ("event", "failure")]
        if new:
            time.sleep(settle)  # let any trailing loss records for the same response arrive
            return [m for m in messages()[before:] if m.get("kind") in ("event", "failure")]
        time.sleep(0.1)
    return []
