"""Edge cases against live PRs (T081; spec User Story 2, scenarios 1-9).

Run after `gca demo scenarios`: for each scenario PR in the run report, wait for the check on its latest head,
then compare every stored line result with the PR's `.gca-expected.json`, and check the head, pending, final and
not-observed behaviour. Needs the demo cluster and GitHub; opt in with GCA_SCENARIOS_REPORT=<report path>.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from tests.privacy.scan import Cluster

pytestmark = pytest.mark.e2e

CHECK = "AI code attribution"


def _gh(*args: str) -> Any:
    out = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120, check=True)
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    path = os.environ.get("GCA_SCENARIOS_REPORT")
    if not path or not Path(path).exists():
        pytest.skip("run `gca demo scenarios --report <path>` and set GCA_SCENARIOS_REPORT")
    return dict(json.loads(Path(path).read_text()))


@pytest.fixture(scope="module")
def cluster(pytestconfig: pytest.Config) -> Cluster:
    return Cluster(
        pytestconfig.getoption("--kube-context"),
        pytestconfig.getoption("--namespace"),
        pytestconfig.getoption("--release"),
    )


def _expected(repo: str, branch: str) -> dict[str, Any]:
    blob = _gh("api", f"repos/{repo}/contents/.gca-expected.json?ref={branch}")
    return dict(json.loads(base64.b64decode(blob["content"])))


def _wait_completed(repo: str, sha: str, timeout: float = 900) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for cr in _gh("api", f"repos/{repo}/commits/{sha}/check-runs")["check_runs"]:
            if cr["name"] == CHECK and cr["status"] == "completed":
                return dict(cr)
        time.sleep(10)
    raise TimeoutError(f"no completed check on {sha[:12]}")


def _head(cluster: Cluster, repo: str, pr: int, sha: str) -> dict[str, Any]:
    return dict(
        json.loads(
            cluster.psql(
                "SELECT json_build_object('id', h.id, 'coverage', h.coverage_status, 'reasons', h.coverage_reasons, "
                "'final', h.is_final, 'status', h.status) FROM change_head h JOIN change c ON c.id = h.change_id "
                f"JOIN repository r ON r.id = c.repository_id WHERE r.full_name = '{repo}' AND c.pr_number = {pr} "
                f"AND h.head_sha = '{sha}'"
            )
        )
    )


def _lines(cluster: Cluster, head_id: str) -> dict[tuple[str, int], tuple[str, str, int | None]]:
    out = {}
    for row in cluster.psql(
        "SELECT file_path || '|' || line_no || '|' || outcome || '|' || tier || '|' || coalesce(credited_github_id::text, '') "
        f"FROM line_result WHERE change_head_id = '{head_id}'"
    ).splitlines():
        path, no, outcome, tier, gid = row.split("|")
        out[(path, int(no))] = (outcome, tier, int(gid) if gid else None)
    return out


def _compare(
    expected: dict[str, Any], lines: dict[tuple[str, int], tuple[str, str, int | None]]
) -> list[str]:
    problems = []
    for path, labels in expected["files"].items():
        for no, label in labels.items():
            got = lines.get((path, int(no)))
            if got is None:
                problems.append(f"{path}:{no} expected {label}, no result stored")
            elif got[0] != label:
                problems.append(f"{path}:{no} expected {label}, got {got[0]} ({got[1]})")
            elif label != "not_observed" and got[2] != expected["credited"][path]:
                problems.append(f"{path}:{no} credited to {got[2]}, expected {expected['credited'][path]}")
    return problems


def _cases(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in report["scenarios"] if not s.get("skipped")]


def test_every_line_matches_its_answer_key(report: dict[str, Any], cluster: Cluster) -> None:
    failures = {}
    for case in _cases(report):
        sha = case["heads"][-1]
        _wait_completed(report["repo"], sha)
        head = _head(cluster, report["repo"], case["pr"], sha)
        expected = _expected(report["repo"], case["branch"])
        problems = _compare(expected, _lines(cluster, head["id"]))
        if head["coverage"] != expected["coverage"]:
            problems.append(f"coverage {head['coverage']}, expected {expected['coverage']}")
        if problems:
            failures[case["scenario"]] = problems[:8]
    assert not failures, json.dumps(failures, indent=2)


def _case(report: dict[str, Any], name: str) -> dict[str, Any]:
    case = next((c for c in report["scenarios"] if c["scenario"] == name), None)
    if case is None or case.get("skipped"):
        pytest.skip(f"{name} wasn't run")
    return case


def test_pending_waits_then_completes(report: dict[str, Any], cluster: Cluster) -> None:  # scenario 6
    case = _case(report, "scn-pending")
    assert case["waiting_seen"], (
        "the check never showed 'Waiting for capture to catch up' while ingest was paused"
    )
    head = _head(cluster, report["repo"], case["pr"], case["heads"][-1])
    assert head["status"] == "complete" and head["coverage"] == "complete"


def test_new_push_keeps_earlier_head(report: dict[str, Any], cluster: Cluster) -> None:  # scenario 9
    case = _case(report, "scn-new-push")
    first, second = (_head(cluster, report["repo"], case["pr"], sha) for sha in case["heads"])
    assert first["status"] == "complete" and second["status"] == "complete"
    first_files = {p for p, _ in _lines(cluster, first["id"])}
    assert "src/scenarios/stock_report.py" not in first_files  # the earlier head keeps its own result
    assert "src/scenarios/stock_report.py" in {p for p, _ in _lines(cluster, second["id"])}


def test_rewritten_history_keeps_attribution(report: dict[str, Any], cluster: Cluster) -> None:  # scenario 5
    case = _case(report, "scn-rewrite")
    assert len(case["heads"]) == 2  # the original head and the rebased, squashed one
    lines = _lines(cluster, _head(cluster, report["repo"], case["pr"], case["heads"][-1])["id"])
    assert sum(1 for v in lines.values() if v[0] == "ai_unmodified") >= 6


def test_unmapped_author_is_not_observed(report: dict[str, Any], cluster: Cluster) -> None:  # scenario 7
    case = _case(report, "scn-unmapped")
    head = _head(cluster, report["repo"], case["pr"], case["heads"][-1])
    lines = _lines(cluster, head["id"])
    legacy = [v for (p, _), v in lines.items() if p == "src/scenarios/legacy_import.py"]
    assert legacy and all(v[0] == "not_observed" and v[2] is None for v in legacy)
    assert any("not observed" in r for r in head["reasons"])


def test_merge_marks_final(report: dict[str, Any], cluster: Cluster) -> None:  # scenario 9 (final at merge)
    # The rewrite PR targets the scenario's own scratch base branch, so merging it never touches main.
    case = _case(report, "scn-rewrite")
    subprocess.run(
        ["gh", "pr", "merge", str(case["pr"]), "--repo", report["repo"], "--squash", "--delete-branch"],
        capture_output=True,
        timeout=120,
        check=True,
    )
    end = time.monotonic() + 180
    while time.monotonic() < end:
        state = cluster.psql(
            f"SELECT c.state || '|' || coalesce(h.head_sha, '') FROM change c JOIN repository r ON r.id = c.repository_id "
            f"LEFT JOIN change_head h ON h.id = c.final_head_id WHERE r.full_name = '{report['repo']}' "
            f"AND c.pr_number = {case['pr']}"
        ).strip()
        if state.startswith("merged|"):
            assert state == f"merged|{case['heads'][-1]}"
            return
        time.sleep(10)
    raise AssertionError(f"PR #{case['pr']} not recorded as merged with its head as final: {state}")
