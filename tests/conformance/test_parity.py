"""Cross-gateway conformance (T063, T112; FR-006, FR-045; R4): every probe fixture, every demo-session step and
every recorded real-traffic response, replayed through agentgateway + ext_proc and through LiteLLM + its callback,
yields identical multisets of
(t, l, x, m, b, p) per capture event and the same loss records. Malformed and truncated streams must be reported
as loss, never dropped silently, on both gateways."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from gca_demo.sessions import marker, sessions

from . import harness as h

CASES: list[tuple[str, str, str]] = [  # (id, api format, request text)
    *((f"fixture-{name}", fmt, f"gca-fixture={name}") for name, fmt in h.FIXTURE_FORMATS.items()),
    *(
        (f"demo-{s.name}-{i}", step.format, marker(s.name, i))
        for s in sessions().values()
        for i, step in enumerate(s.steps)
    ),
    *h.corpus_cases(),
]


@pytest.fixture(scope="module")
def results() -> Iterator[dict[str, dict[str, Any]]]:
    if shutil.which("uv") is None:
        pytest.skip("uv is required to run the pinned LiteLLM")
    tmp = Path(tempfile.mkdtemp(prefix="gca-conformance-"))
    keys = h.write_keys(tmp / "keys")
    with h.stack(keys, [h.CREDENTIAL], h.respond) as s:
        res: dict[str, dict[str, Any]] = {}
        for case_id, fmt, text in CASES:
            res[case_id] = {
                gw: h.canonical(h.replay(s.send(gw, h.CREDENTIAL), lambda gw=gw: s.messages(gw), fmt, text))
                for gw in ("agentgateway", "litellm")
            }
        yield res
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.parametrize("case_id", [c[0] for c in CASES])
def test_same_capture_on_both_gateways(results: dict[str, dict[str, Any]], case_id: str) -> None:
    ag, ll = results[case_id]["agentgateway"], results[case_id]["litellm"]
    assert ag["events"] or ag["failures"], f"agentgateway reported nothing for {case_id}"
    assert ll["events"] or ll["failures"], f"LiteLLM reported nothing for {case_id}"
    assert [e["lines"] for e in ag["events"]] == [e["lines"] for e in ll["events"]], case_id
    assert [e["status"] for e in ag["events"]] == [e["status"] for e in ll["events"]], case_id
    assert ag["failures"] == ll["failures"], case_id


@pytest.mark.parametrize("case_id", [c[0] for c in h.corpus_cases()])
def test_recorded_traffic_is_captured_as_the_library_reads_it(
    results: dict[str, dict[str, Any]], case_id: str
) -> None:
    """Real traffic (FR-045): each gateway captures every line the library reads from the recording, and reports
    no loss for a complete response."""
    ref = next(text for cid, _, text in h.corpus_cases() if cid == case_id).split("=", 1)[1]
    want = h.corpus_lines(ref)
    for gw, r in results[case_id].items():
        got = sorted(line for e in r["events"] for line in e["lines"])
        assert got == want, (gw, case_id, len(got), len(want))
        assert r["failures"] == [] and all(e["status"] == "captured" for e in r["events"]), (
            gw,
            r["failures"],
        )


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
