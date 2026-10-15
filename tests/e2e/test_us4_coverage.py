"""End-to-end test for User Story 4 (T093; SC-005, FR-005a, FR-022, SC-010).

Runs against the demo install that's already up (`make demo`), with whichever gateway it has:

- (a) inject truncated and schema-deviant responses; the coverage view counts each with its cause (SC-005);
- (b) take capture away mid-traffic (agentgateway: scale the capture processor to 0; LiteLLM: stop NATS); every
  gateway request still succeeds (FR-005a);
- (c) once restored, a `heartbeat_missed` loss is on record, and a PR whose window overlaps it is incomplete;
- (d) agentgateway only: a 2-second delay in background parsing leaves client p95 completion time within SC-010,
  and a delay on the echo path still lets every request complete (slower: R2 found no gateway-side timeout).

Opt in with GCA_E2E=1 and GCA_E2E_REPO=OWNER/NAME. It opens and closes one PR, and afterwards deletes the capture
loss it caused, so later demo PRs on this install aren't marked incomplete because of the test.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from gca_demo.sessions import demo_sessions, marker
from tests.privacy.scan import Cluster

from .harness import GATEWAY_URL, close_pr, run, wait_for_check, wait_for_key

pytestmark = pytest.mark.e2e

FAULTS = {"truncated": 3, "unexpected_format": 2}
SC010 = 1.05  # p95 completion time may grow by at most 5%
NOISE_S = 0.05  # kind on a laptop: absolute slack under which timing differences are noise


@dataclass
class Env:
    cluster: Cluster
    gateway: str
    repo: str
    key: str
    developer_id: str
    started: str  # database time when the test began


def _poll(check: Callable[[], Any], timeout: float, every: float = 3.0) -> Any:
    end = time.monotonic() + timeout
    while True:
        value = check()
        if value or time.monotonic() > end:
            return value
        time.sleep(every)


@pytest.fixture(scope="module")
def env(pytestconfig: pytest.Config) -> Iterator[Env]:
    if os.environ.get("GCA_E2E") != "1":
        pytest.skip(
            "end-to-end test: set GCA_E2E=1 (uses the running demo install, opens a PR in GCA_E2E_REPO)"
        )
    repo = os.environ.get("GCA_E2E_REPO")
    if not repo:
        pytest.skip("set GCA_E2E_REPO=OWNER/NAME")
    cluster = Cluster(
        pytestconfig.getoption("--kube-context"),
        pytestconfig.getoption("--namespace"),
        pytestconfig.getoption("--release"),
    )
    has_extproc = cluster.kubectl("get", "deploy", f"{cluster.fullname}-capture-extproc", check=False)
    gateway = "agentgateway" if has_extproc.strip() else "litellm"
    user = json.loads(run(["gh", "api", "user"]))
    key = (
        cluster.kubectl(
            "exec", f"deploy/{cluster.fullname}-portal", "--", "python", "-m", "gca_portal.admin_cli",
            "issue-credential", "--github-id", str(user["id"]), "--github-login", user["login"],
        )
        .decode()
        .strip()
        .splitlines()[-1]
    )  # fmt: skip
    wait_for_key(key)
    dev = cluster.psql(f"SELECT id FROM developer WHERE github_id = {int(user['id'])}").strip()
    started = cluster.psql("SELECT now()").strip()
    yield Env(cluster, gateway, repo, key, dev, started)
    removed = cluster.psql(
        f"DELETE FROM capture_loss WHERE period_start >= TIMESTAMPTZ '{started}' - interval '1 minute' "
        "RETURNING cause"
    )
    print(f"removed {len(removed.split())} capture-loss rows the test caused")


def _loss(env: Env, where: str) -> dict[str, int]:
    rows = env.cluster.psql(
        f"SELECT cause || '=' || sum(count) FROM capture_loss WHERE {where} GROUP BY cause"
    ).split()
    return {k: int(v) for k, v in (r.split("=") for r in rows)}


def _view(env: Env) -> dict[str, int]:
    rows = env.cluster.psql(
        "SELECT cause || '=' || sum(lost) FROM v_coverage_daily WHERE day >= date_trunc('day', now()) GROUP BY cause"
    ).split()
    return {k: int(v) for k, v in (r.split("=") for r in rows)}


def _anthropic_step() -> str:
    for s in demo_sessions().values():
        for i, step in enumerate(s.steps):
            if step.format == "anthropic_messages":
                return marker(s.name, i)
    raise RuntimeError("no Anthropic step in the demo sessions")


def _request(client: httpx.Client, key: str, text: str) -> tuple[int, bytes, float]:
    t0 = time.perf_counter()
    r = client.post(
        f"{GATEWAY_URL}/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "user-agent": "gca-e2e"},
        json={
            "model": "demo-anthropic",
            "max_tokens": 1024,
            "stream": True,
            "messages": [{"role": "user", "content": text}],
        },
    )
    return r.status_code, r.content, time.perf_counter() - t0


def _traffic(env: Env, n: int) -> list[float]:
    """n streamed Anthropic responses with a tool call; each must succeed in full. Returns completion times."""
    text = _anthropic_step()
    times = []
    with httpx.Client(timeout=120) as client:
        for _ in range(n):
            status, body, took = _request(client, env.key, text)
            assert status == 200 and b"message_stop" in body[-300:], (status, body[-300:])
            times.append(took)
    return times


def _p95(times: list[float]) -> float:
    return statistics.quantiles(times, n=20)[-1]


# ----------------------------------------------------------------------------------------------- (a)
def test_injected_faults_are_counted_with_their_cause(env: Env) -> None:
    mine = f"developer_id = '{env.developer_id}'"
    before, view_before = _loss(env, mine), _view(env)
    t0 = env.cluster.psql("SELECT now()").strip()
    spec = ",".join(f"{k}={v}" for k, v in FAULTS.items())
    run(
        ["uv", "run", "gca", "demo", "run", "--repo", env.repo, "--gateway", env.gateway,
         "--inject-faults", spec, "--faults-only"],
        env={"GCA_CREDENTIAL": env.key},
        timeout=300,
    )  # fmt: skip

    def delta() -> dict[str, int]:
        after = _loss(env, mine)
        return {k: after.get(k, 0) - before.get(k, 0) for k in FAULTS}

    _poll(lambda: delta()["truncated"] >= FAULTS["truncated"], 120)
    time.sleep(10)  # let anything late arrive, so an over-count shows
    got = delta()
    assert got["truncated"] == FAULTS["truncated"]
    if env.gateway == "agentgateway":
        assert got["unexpected_format"] == FAULTS["unexpected_format"]
    else:
        # LiteLLM parses the stream itself and hands capture its own object. A deviation it tolerates never
        # reaches capture: then the response must have been captured in full instead. Either way, none is lost.
        captured = int(
            env.cluster.psql(
                f"SELECT count(*) FROM capture_event WHERE developer_id = '{env.developer_id}' "
                f"AND received_at >= TIMESTAMPTZ '{t0}' AND status = 'captured' AND api_format = 'openai_responses' "
                "AND tool_call_count > 0"
            )
        )
        assert got["unexpected_format"] + captured == FAULTS["unexpected_format"]
    view_after = _view(env)
    for cause, n in got.items():  # the coverage view reports exactly what was recorded
        assert view_after.get(cause, 0) - view_before.get(cause, 0) == n, cause


# ----------------------------------------------------------------------------------------------- (b), (c)
def _take_capture_away(env: Env) -> tuple[str, str, int]:
    fn = env.cluster.fullname
    kind, name = (
        ("deployment", f"{fn}-capture-extproc")
        if env.gateway == "agentgateway"
        else ("statefulset", f"{env.cluster.release}-nats")
    )
    replicas = int(env.cluster.kubectl("get", kind, name, "-o", "jsonpath={.spec.replicas}").decode() or 1)
    env.cluster.kubectl("scale", kind, name, "--replicas=0")
    selector = json.loads(
        env.cluster.kubectl("get", kind, name, "-o", "jsonpath={.spec.selector.matchLabels}")
    )
    labels = ",".join(f"{k}={v}" for k, v in selector.items())
    env.cluster.kubectl("wait", "--for=delete", "pod", "-l", labels, "--timeout=180s", check=False)
    return kind, name, replicas


def _restore(env: Env, kind: str, name: str, replicas: int) -> None:
    env.cluster.kubectl("scale", kind, name, f"--replicas={replicas}")
    env.cluster.kubectl("rollout", "status", f"{kind}/{name}", "--timeout=300s")


def test_capture_outage_fails_open_and_marks_overlapping_prs_incomplete(env: Env) -> None:
    missed = (
        f"cause = 'heartbeat_missed' AND period_start >= TIMESTAMPTZ '{env.started}' - interval '1 minute'"
    )
    kind, name, replicas = _take_capture_away(env)
    try:
        times = _traffic(env, 20)  # (b): every request succeeds with capture gone
        assert len(times) == 20
        assert _poll(lambda: _loss(env, missed), 120), "no heartbeat_missed loss while capture was down"
    finally:
        _restore(env, kind, name, replicas)
    assert _poll(
        lambda: (
            env.cluster.psql(
                f"SELECT count(*) FROM capture_loss WHERE {missed} AND period_end IS NULL"
            ).strip()
            == "0"
        ),
        180,
    ), "the loss didn't close after capture came back"

    out = run(
        ["uv", "run", "gca", "demo", "run", "--repo", env.repo, "--gateway", env.gateway],
        env={"GCA_CREDENTIAL": env.key},
        timeout=900,
    )
    m = re.search(r"Opened https://github\.com/[^\s]+/pull/(\d+)", out)
    assert m, out[-800:]
    pr = int(m.group(1))
    try:
        sha = run(
            ["gh", "pr", "view", str(pr), "--repo", env.repo, "--json", "headRefOid", "-q", ".headRefOid"]
        )
        check = wait_for_check(env.repo, sha.strip())
        head = json.loads(
            env.cluster.psql(
                "SELECT json_build_object('coverage', h.coverage_status, 'reasons', h.coverage_reasons) "
                "FROM change_head h JOIN change c ON c.id = h.change_id JOIN repository r ON r.id = c.repository_id "
                f"WHERE r.full_name = '{env.repo}' AND c.pr_number = {pr} AND h.head_sha = '{sha.strip()}'"
            )
        )
        assert head["coverage"] == "incomplete", head
        assert any("capture wasn't reporting" in r for r in head["reasons"]), head["reasons"]
        assert "coverage: incomplete" in check["output"]["title"]
    finally:
        close_pr(env.repo, pr)


# ----------------------------------------------------------------------------------------------- (d)
def _set_env(env: Env, **values: str) -> None:
    name = f"deployment/{env.cluster.fullname}-capture-extproc"
    pairs = [f"{k}={v}" if v else f"{k}-" for k, v in values.items()]
    env.cluster.kubectl("set", "env", name, *pairs)
    env.cluster.kubectl("rollout", "status", name, "--timeout=300s")
    time.sleep(10)  # the gateway's connections move to the new pods


def test_slow_capture_doesnt_slow_developers(env: Env) -> None:
    if env.gateway != "agentgateway":
        pytest.skip("LiteLLM captures in a callback after the response is sent; there's no echo path to slow")
    _traffic(env, 5)  # warm up
    baseline = _traffic(env, 40)
    try:
        _set_env(env, GCA_CAPTURE_TEST_PARSE_DELAY_SECONDS="2")
        slow_parse = _traffic(env, 40)
        assert _p95(slow_parse) <= _p95(baseline) * SC010 + NOISE_S, (_p95(baseline), _p95(slow_parse))
        _set_env(env, GCA_CAPTURE_TEST_PARSE_DELAY_SECONDS="", GCA_CAPTURE_TEST_ECHO_DELAY_SECONDS="0.05")
        slow_echo = _traffic(env, 5)  # every response still completes in full, only later
        assert min(slow_echo) > statistics.median(baseline)
    finally:
        _set_env(env, GCA_CAPTURE_TEST_PARSE_DELAY_SECONDS="", GCA_CAPTURE_TEST_ECHO_DELAY_SECONDS="")
