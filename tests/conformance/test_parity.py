"""Cross-gateway conformance (T063; FR-006; R4): every probe fixture and every demo-session step, replayed
through agentgateway + ext_proc and through LiteLLM + its callback, yields identical multisets of
(t, l, x, m, b, p) per capture event and the same loss records. Malformed and truncated streams must be reported
as loss, never dropped silently, on both gateways."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from gca_demo.sessions import marker, sessions

from . import harness as h

CASES: list[tuple[str, str, str]] = [  # (id, api format, request text)
    *((f"fixture-{name}", fmt, f"gca-fixture={name}") for name, fmt in h.FIXTURE_FORMATS.items()),
    *(
        (f"demo-{s.name}-{i}", step.format, marker(s.name, i))
        for s in sessions().values()
        for i, step in enumerate(s.steps)
    ),
]


@pytest.fixture(scope="module")
def results() -> Iterator[dict[str, dict[str, Any]]]:
    if shutil.which("uv") is None:
        pytest.skip("uv is required to run the pinned LiteLLM")
    tmp = Path(tempfile.mkdtemp(prefix="gca-conformance-"))
    keys = h.write_keys(tmp / "keys")
    upstream = h.Upstream()
    extproc = h.ExtProc(keys)
    ag_port, ll_port = h.free_port(), h.free_port()
    (tmp / "agentgateway.yaml").write_text(
        yaml.safe_dump(h.agentgateway_config(ag_port, extproc.port, upstream.port))
    )
    ag = h.Proc(
        [str(h.agentgateway_binary()), "-f", str(tmp / "agentgateway.yaml")], {}, tmp / "agentgateway.log"
    )
    (tmp / "conformance_callback.py").write_text(h.CALLBACK)
    (tmp / "litellm.yaml").write_text(yaml.safe_dump(h.litellm_config(upstream.port)))
    out = h.FileCollector(tmp / "litellm-messages.jsonl")
    ll = h.Proc(
        [
            "uv",
            "run",
            "--quiet",
            "--with",
            h.LITELLM,
            "litellm",
            "--config",
            str(tmp / "litellm.yaml"),
            "--port",
            str(ll_port),
        ],
        {
            "PYTHONPATH": str(tmp),
            "GCA_KEYS_DIR": str(keys),
            "GCA_CONFORMANCE_OUT": str(out.path),
            "LITELLM_LOG": "ERROR",
        },
        tmp / "litellm.log",
    )
    try:
        h.wait_port(ag_port, 60, ag.proc)
        h.wait_port(ll_port, 900, ll.proc)  # the first run installs LiteLLM into uv's cache
        send_ag = h.sender(f"http://127.0.0.1:{ag_port}", h.AG_KEY, "agentgateway")
        send_ll = h.sender(f"http://127.0.0.1:{ll_port}", h.LL_MASTER, "litellm")
        res: dict[str, dict[str, Any]] = {}
        for case_id, fmt, text in CASES:
            res[case_id] = {
                "agentgateway": h.replay(send_ag, lambda: list(extproc.messages), fmt, text),
                "litellm": h.replay(send_ll, lambda: out.messages, fmt, text),
            }
        yield res
    finally:
        ag.stop()
        ll.stop()
        extproc.stop()
        upstream.stop()


@pytest.mark.parametrize("case_id", [c[0] for c in CASES])
def test_same_capture_on_both_gateways(results: dict[str, dict[str, Any]], case_id: str) -> None:
    ag, ll = results[case_id]["agentgateway"], results[case_id]["litellm"]
    assert ag["events"] or ag["failures"], f"agentgateway reported nothing for {case_id}"
    assert ll["events"] or ll["failures"], f"LiteLLM reported nothing for {case_id}"
    assert [e["lines"] for e in ag["events"]] == [e["lines"] for e in ll["events"]], case_id
    assert [e["status"] for e in ag["events"]] == [e["status"] for e in ll["events"]], case_id
    assert ag["failures"] == ll["failures"], case_id


def test_truncated_stream_is_reported_as_loss(results: dict[str, dict[str, Any]]) -> None:
    for gw, r in results["fixture-anthropic_truncated"].items():
        assert "truncated" in r["failures"] or any(e["status"] == "partial" for e in r["events"]), gw


def test_report(results: dict[str, dict[str, Any]]) -> None:
    """Print what each gateway captured per case (visible with -s; kept in CI logs)."""
    print(f"\n{'case':34} {'agentgateway':30} {'litellm':30}")
    for case_id, r in results.items():
        cells = []
        for gw in ("agentgateway", "litellm"):
            ev = r[gw]["events"]
            lines = "+".join(str(len(e["lines"])) for e in ev) or "-"
            status = ",".join(e["status"] for e in ev) or "-"
            loss = ",".join(r[gw]["failures"]) or "none"
            cells.append(f"{lines} lines {status} loss={loss}")
        print(f"{case_id:34} {cells[0]:30} {cells[1]:30}")
    assert all(r["agentgateway"]["events"] for k, r in results.items() if not k.endswith("truncated"))
