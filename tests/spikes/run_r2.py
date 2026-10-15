"""T038 driver: validate agentgateway 1.6.0 extProc behaviour for research R2. Prints a JSON report.

Usage: python run_r2.py <agentgateway-binary> <python-with-grpc-and-xds-protos>
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROBE = ROOT / ".specify/assessments/gateway-code-attribution/probes/streamed-tool-calls"
KEY = "gca_spike_key_1"
REQ = {
    "openai_chat": (
        "/v1/chat/completions",
        {"model": "mock-openai", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
        {},
    ),
    "openai_responses": ("/v1/responses", {"model": "mock-openai", "stream": True, "input": "hi"}, {}),
    "anthropic": (
        "/v1/messages",
        {
            "model": "mock-anthropic",
            "stream": True,
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "hi"}],
        },
        {"anthropic-version": "2023-06-01"},
    ),
}


def wait_port(port: int, timeout: float = 20) -> None:
    import socket

    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"port {port} did not open")


def fetch(
    base: str,
    path: str,
    body: dict,
    headers: dict,
    key: str | None = KEY,
    header_name: str = "authorization",
    timeout: float = 60,
) -> tuple[int, bytes, float]:
    h = {"content-type": "application/json", **headers}
    if key:
        h[header_name] = f"Bearer {key}" if header_name == "authorization" else key
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST", headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            parts: list[bytes] = []
            while chunk := r.read1(65536):
                parts.append(chunk)
                if time.time() - t0 > timeout:  # total deadline, not just per-read inactivity
                    return -1, b"".join(parts), time.time() - t0
            return r.status, b"".join(parts), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - t0
    except TimeoutError:
        return -1, b"", time.time() - t0


def start(
    cmd: list[str], env: dict | None = None, cwd: Path | None = None, log: Path | None = None
) -> subprocess.Popen:
    out = open(log, "wb") if log else subprocess.DEVNULL
    return subprocess.Popen(
        cmd, cwd=cwd, env={**os.environ, **(env or {})}, stdout=out, stderr=subprocess.STDOUT
    )


def main() -> None:
    ag_bin, grpc_py = sys.argv[1], sys.argv[2]
    tmp = Path(tempfile.mkdtemp(prefix="r2-"))
    out = tmp / "proc.jsonl"
    procs: list[subprocess.Popen] = []
    report: dict = {}
    try:
        procs.append(start([sys.executable, "mock_upstream.py", "18090"], cwd=PROBE, env={"CHUNK": "7"}))
        wait_port(18090)
        proc = start(
            [grpc_py, str(HERE / "extproc_echo.py")], env={"SPIKE_OUT": str(out)}, log=tmp / "proc.log"
        )
        procs.append(proc)
        wait_port(9000)
        ag = start([ag_bin, "-f", str(HERE / "r2_agentgateway.yaml")], log=tmp / "ag.log")
        procs.append(ag)
        wait_port(13090)
        time.sleep(0.5)

        # (a) byte identity and (b) processor saw every byte, per format
        fmt_results = {}
        for fmt, (path, body, hdr) in REQ.items():
            _, direct, _ = fetch("http://127.0.0.1:18090", path, {**body, "model": "mock"}, hdr, key=None)
            status, via, secs = fetch("http://127.0.0.1:13090", path, body, hdr)
            fmt_results[fmt] = {
                "status": status,
                "identical_to_direct": via == direct,
                "bytes": len(via),
                "sha256": hashlib.sha256(via).hexdigest(),
                "seconds": round(secs, 3),
            }
        time.sleep(0.5)
        seen = [json.loads(line) for line in out.read_text().splitlines()] if out.exists() else []
        by_sha = {s["sha256"]: s for s in seen}
        for fmt, r in fmt_results.items():
            s = by_sha.get(r["sha256"])
            r["processor_saw_all_bytes"] = s is not None
            r["processor_chunks"] = s["chunks"] if s else None
            r["metadata"] = s["metadata"] if s else None
        report["a_b_d_formats"] = fmt_results

        # API key enforcement and alternative headers
        report["no_key_status"] = fetch("http://127.0.0.1:13090", *REQ["openai_chat"][:2], {}, key=None)[0]
        report["x_api_key_status"] = fetch(
            "http://127.0.0.1:13090", *REQ["anthropic"][:2], REQ["anthropic"][2], header_name="x-api-key"
        )[0]
        report["x_goog_api_key_status"] = fetch(
            "http://127.0.0.1:13090", *REQ["openai_chat"][:2], {}, header_name="x-goog-api-key"
        )[0]
        report["wrong_key_status"] = fetch("http://127.0.0.1:13090", *REQ["openai_chat"][:2], {}, key="nope")[
            0
        ]

        # (c) kill the processor mid-stream: slow upstream so the stream is long
        procs.append(start([sys.executable, "mock_upstream.py", "18091"], cwd=PROBE, env={"CHUNK": "2"}))
        wait_port(18091)
        result: dict = {}

        def long_request() -> None:
            # reuse anthropic route but point at the slower upstream through a direct comparison afterwards
            result["via"] = fetch("http://127.0.0.1:13090", *REQ["anthropic"][:2], REQ["anthropic"][2])

        t = threading.Thread(target=long_request)
        t.start()
        time.sleep(0.15)
        proc.send_signal(signal.SIGKILL)
        t.join(60)
        _, direct, _ = fetch(
            "http://127.0.0.1:18090",
            REQ["anthropic"][0],
            {**REQ["anthropic"][1], "model": "mock"},
            REQ["anthropic"][2],
            key=None,
        )
        status, via, secs = result.get("via", (None, b"", 0))
        report["c_kill_processor_midstream"] = {
            "status": status,
            "identical_to_direct": via == direct,
            "seconds": round(secs, 3),
        }
        report["c_after_kill_new_request_status"] = fetch(
            "http://127.0.0.1:13090", *REQ["openai_chat"][:2], {}
        )[0]

        # (e) slow processor: 0.5 s delay on each echo; client gives up after 10 s
        slow = start(
            [grpc_py, str(HERE / "extproc_echo.py")],
            env={"SPIKE_OUT": str(tmp / "slow.jsonl"), "ECHO_DELAY": "0.5"},
        )
        procs.append(slow)
        wait_port(9000)
        time.sleep(0.5)
        status, via, secs = fetch("http://127.0.0.1:13090", *REQ["openai_chat"][:2], {}, timeout=10)
        report["e_slow_processor_0_5s_per_chunk"] = {
            "status": "client timed out (stalled)" if status == -1 else status,
            "bytes_received": len(via),
            "seconds": round(secs, 1),
        }
    finally:
        for p in procs:
            p.kill()
        report["logs_dir"] = str(tmp)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
