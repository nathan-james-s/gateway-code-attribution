"""End-to-end test for User Story 1 (T065; SC-001, FR-006).

For each gateway in turn: install the demo, issue a credential (operator command, no browser), run
`gca demo run` against GCA_E2E_REPO, wait for the check run, then assert the outcomes, coverage, reporting view
and time to first result. With both gateways, the per-line outcomes must be identical. Opt in with GCA_E2E=1.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from tests.privacy.scan import Cluster

from .harness import DemoRun, close_pr, demo_run, github_files, workdir

pytestmark = pytest.mark.e2e

TIME_LIMIT_S = 30 * 60  # SC-001, excluding App creation


@pytest.fixture(scope="session")
def runs(pytestconfig: pytest.Config) -> Iterator[dict[str, DemoRun]]:
    if os.environ.get("GCA_E2E") != "1":
        pytest.skip("end-to-end test: set GCA_E2E=1 (reinstalls the demo, opens PRs in GCA_E2E_REPO)")
    repo = os.environ.get("GCA_E2E_REPO")
    if not repo:
        pytest.skip(
            "set GCA_E2E_REPO=OWNER/NAME (a repository with the sample project and the App installed)"
        )
    choice = pytestconfig.getoption("--gateway")
    gateways = ["agentgateway", "litellm"] if choice == "both" else [choice]
    cluster = Cluster(
        pytestconfig.getoption("--kube-context"),
        pytestconfig.getoption("--namespace"),
        pytestconfig.getoption("--release"),
    )
    tmp = workdir()
    values, secret = github_files(tmp)
    done: dict[str, DemoRun] = {}
    try:
        for i, gw in enumerate(gateways):
            done[gw] = demo_run(cluster, gw, repo, values, secret, clear_captures=i > 0, logdir=tmp)
        yield done
    finally:
        for r in done.values():
            close_pr(repo, r.pr)


def test_every_outcome_appears(runs: dict[str, DemoRun]) -> None:
    for gw, r in runs.items():
        c = r.counts
        assert c["ai_unmodified"] > 0, gw
        assert c["ai_modified_anchored"] > 0, gw
        assert c["ai_modified_broad"] > 0, gw  # see gca_demo sessions: the moved-and-adapted line
        assert c["human"] > 0, gw
        assert c["indeterminate"] > 0, gw
        assert c["not_observed"] == 0, gw


def test_coverage_complete_and_check_neutral(runs: dict[str, DemoRun]) -> None:
    for gw, r in runs.items():
        assert r.coverage == "complete", gw
        assert r.check["conclusion"] == "neutral", gw
        assert r.check["output"]["title"].startswith("AI "), gw


def test_change_reaches_reporting_view(runs: dict[str, DemoRun]) -> None:
    for gw, r in runs.items():
        assert r.summary_rows == 1, gw


def test_time_to_first_result(runs: dict[str, DemoRun]) -> None:
    for gw, r in runs.items():
        print(f"{gw}: install start to completed check {r.elapsed_s / 60:.1f} min")
        assert r.elapsed_s <= TIME_LIMIT_S, f"{gw}: {r.elapsed_s / 60:.1f} min"


def test_identical_outcomes_across_gateways(runs: dict[str, DemoRun]) -> None:
    if len(runs) < 2:
        pytest.skip("parity needs both gateways (--gateway both)")
    a, b = runs["agentgateway"], runs["litellm"]
    assert a.lines and a.lines.keys() == b.lines.keys()
    differ = {k: (a.lines[k], b.lines[k]) for k in a.lines if a.lines[k] != b.lines[k]}
    assert not differ, f"{len(differ)} lines differ, e.g. {list(differ.items())[:5]}"
