"""Capture's overhead on response completion time at load (T114; SC-010, research R2).

For each gateway, runs the same Locust load (tests/perf/locustfile.py: N developers, think times, streamed
tool-call responses paced like a model) twice, once without capture and once with it, and compares the p95
response completion time. SC-010 allows capture to add at most 5%. With capture on it also checks that capture
kept up: every response the gateway served produced a capture message, and none was reported lost.

Runs locally through gca_eval.gateways (the real agentgateway binary with our ext_proc server, and the pinned
LiteLLM with our callback), like conformance and the eval. Capture runs one ext_proc worker here; a default
install runs two replicas of two, so this errs toward overstating the overhead.

    uv run --group perf python tests/perf/gateway_overhead.py --users 500 --duration 300
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from gca_demo.sessions import marker, sessions
from gca_eval.gateways import Credential, stack

HERE = Path(__file__).resolve().parent
SECRET = b"\x5a" * 32


def _keys(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "1").write_text(base64.b64encode(SECRET).decode())
    (directory / "active").write_text("1")
    return directory


def _credentials(n: int) -> list[Credential]:
    return [Credential(f"sk-gca-perf-{i:05d}", str(uuid.UUID(int=i + 1)), 900_000 + i) for i in range(n)]


def _percentile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


def _stats(stats_csv: Path, times_file: Path) -> dict[str, Any]:
    with stats_csv.open() as fh:
        row = next(r for r in csv.DictReader(fh) if r["Name"] == "Aggregated")
    times = [float(x) for x in times_file.read_text().split()]
    return {
        "requests": int(row["Request Count"]),
        "failures": int(row["Failure Count"]),
        "p50_ms": _percentile(times, 0.50),
        "p95_ms": _percentile(times, 0.95),
        "mean_ms": round(sum(times) / len(times), 1),
    }


def _settled(s: Any, gateway: str, timeout: float = 30.0) -> int:
    """The number of capture messages once it stops growing (the warm-up's captures arrive after its responses)."""
    import time

    last, deadline = -1, time.monotonic() + timeout
    while time.monotonic() < deadline:
        n = len(s.messages(gateway))
        if n == last:
            return n
        last = n
        time.sleep(1.0)
    return last


def run_one(gateway: str, capture: bool, args: argparse.Namespace, work: Path) -> dict[str, Any]:
    creds = _credentials(args.users)
    cred_file = work / "credentials.json"
    cred_file.write_text(json.dumps([{"key": c.key, "credential_id": c.credential_id} for c in creds]))
    with stack(
        _keys(work / "keys"),
        creds,
        lambda fmt, path, body: None,  # the demo model answers every step
        (gateway,),
        capture=capture,
        stream_seconds=args.stream_seconds,
    ) as s:
        send = s.send(gateway, creds[0])
        steps = [
            (step.format, marker(se.name, i)) for se in sessions().values() for i, step in enumerate(se.steps)
        ]
        for fmt, text in steps[: args.warmup]:  # first requests load code paths and connections
            send(fmt, text)
        warm = _settled(s, gateway)
        prefix = work / f"{gateway}-{'on' if capture else 'off'}"
        times_file = Path(f"{prefix}_times.txt")
        env = {
            **os.environ,
            "GCA_PERF_TIMES": str(times_file),
            "GCA_PERF_GATEWAY": gateway,
            "GCA_PERF_CREDENTIALS": str(cred_file),
            "GCA_PERF_THINK": args.think,
        }
        subprocess.run(
            [sys.executable, "-m", "locust", "-f", str(HERE / "locustfile.py"), "--headless",
             "-u", str(args.users), "-r", str(args.spawn_rate), "-t", f"{args.duration}s",
             "--host", f"http://127.0.0.1:{s.ports[gateway]}", "--csv", str(prefix), "--only-summary",
             "--stop-timeout", "120", "--loglevel", "WARNING"],
            env=env,
            check=False,
        )  # fmt: skip
        result = {"gateway": gateway, "capture": capture, **_stats(Path(f"{prefix}_stats.csv"), times_file)}
        if capture:
            msgs = s.messages(gateway)[: _settled(s, gateway)][warm:]
            events = sum(
                1 for m in msgs if m.get("kind") == "event" and not m.get("part", {}).get("index", 1) > 1
            )
            lost = sum(int(m.get("count", 1)) for m in msgs if m.get("kind") == "failure")
            result.update(captured_events=events, reported_loss=lost)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gateways", default="agentgateway,litellm")
    ap.add_argument("--users", type=int, default=500, help="active developers (SC-013: 500)")
    ap.add_argument("--spawn-rate", type=float, default=25)
    ap.add_argument("--duration", type=int, default=300, help="seconds of load per run")
    ap.add_argument("--think", default="10,60", help="min,max seconds between a developer's requests")
    ap.add_argument("--stream-seconds", type=float, default=2.0, help="how long the model takes per response")
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--max-overhead", type=float, default=0.05, help="SC-010: 5%%")
    ap.add_argument("--out", type=Path, default=HERE / "results" / "gateway_overhead.json")
    args = ap.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="gca-perf-"))
    runs = [run_one(gw, cap, args, work) for gw in args.gateways.split(",") for cap in (False, True)]
    report: dict[str, Any] = {"settings": {k: v for k, v in vars(args).items() if k != "out"}, "runs": runs}
    ok = True
    for gw in args.gateways.split(","):
        off = next(r for r in runs if r["gateway"] == gw and not r["capture"])
        on = next(r for r in runs if r["gateway"] == gw and r["capture"])
        overhead = round(on["p95_ms"] / off["p95_ms"] - 1, 4) if off["p95_ms"] else None
        passed = (
            overhead is not None
            and overhead <= args.max_overhead
            and on["failures"] == 0
            and off["failures"] == 0
            and on.get("reported_loss", 0) == 0
            and on.get("captured_events", 0) >= on["requests"] - on["failures"]
        )
        report[gw] = {"p95_overhead": overhead, "passed": passed}
        ok &= passed
        print(
            f"{gw:12} p95 {off['p95_ms']:.0f} ms without capture, {on['p95_ms']:.0f} ms with it: "
            f"overhead {overhead:+.1%}; {on['requests']} requests, {on.get('captured_events', 0)} captured, "
            f"{on.get('reported_loss', 0)} lost, {on['failures'] + off['failures']} failed -> "
            f"{'PASS' if passed else 'FAIL'}"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
