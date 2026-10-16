"""T097: `gca attribute` on a local clone gives the PR check's per-line results for the same head (User Story 5).

Takes the most recent attributed head of a PR in GCA_E2E_REPO from the running demo install, exports the
candidates the PR check matched it against (captured lines of its credited developers inside the matching window;
fingerprints only, no content), the fingerprint keys and the exclusion rules, then runs `gca attribute` on a fresh
clone and compares every line's outcome, tier and credited account with the stored `LineResult` rows.

Opt in with GCA_E2E=1 and GCA_E2E_REPO=OWNER/NAME. Keys go to a private temporary directory removed afterwards.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.privacy.scan import Cluster

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cluster(pytestconfig: pytest.Config) -> Cluster:
    if os.environ.get("GCA_E2E") != "1" or not os.environ.get("GCA_E2E_REPO"):
        pytest.skip("set GCA_E2E=1 and GCA_E2E_REPO=OWNER/NAME (a demo install with an attributed PR)")
    return Cluster(
        pytestconfig.getoption("--kube-context"),
        pytestconfig.getoption("--namespace"),
        pytestconfig.getoption("--release"),
    )


@pytest.fixture
def workdir() -> Iterator[Path]:
    d = Path(tempfile.mkdtemp(prefix="gca-cli-"))
    d.chmod(0o700)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _json(cluster: Cluster, sql: str) -> Any:
    return json.loads(cluster.psql(sql) or "null")


def _u32(x: int) -> int:
    return x % 2**32  # minhash is stored as int32 (gca_core.db.base.u32_to_i32)


def _export_captures(cluster: Cluster, head: dict[str, Any], path: Path) -> int:
    """The PR check's candidates (worker._CANDIDATES) for each credited account, as a `gca attribute` captures file."""
    rows = _json(
        cluster,
        f"""
        WITH accounts AS (
            SELECT DISTINCT l.credited_github_id AS gid,
                   coalesce((SELECT o.developer_id FROM identity_override o WHERE o.github_id = l.credited_github_id),
                            (SELECT d.id FROM developer d WHERE d.github_id = l.credited_github_id)) AS dev
            FROM line_result l WHERE l.change_head_id = '{head["id"]}' AND l.credited_github_id IS NOT NULL
        )
        SELECT coalesce(json_agg(json_build_object(
            'github_id', a.gid, 'capture_event_id', cl.capture_event_id::text, 'alg', cl.alg, 'key_gen', cl.key_gen,
            'tool_call_ordinal', cl.tool_call_ordinal, 'line_ordinal', cl.line_ordinal,
            'exact_fp', encode(cl.exact_fp, 'base64'), 'minhash', cl.minhash,
            'path_suffix_fps', (SELECT coalesce(json_agg(encode(p, 'base64')), '[]') FROM unnest(cl.path_suffix_fps) p),
            'lsh_bands', (SELECT coalesce(json_agg(encode(int8send(b.v), 'base64') ORDER BY b.n), '[]')
                          FROM unnest(cl.bands) WITH ORDINALITY AS b(v, n))
        )), '[]')
        FROM accounts a
        JOIN captured_line cl ON cl.developer_id = a.dev
        WHERE cl.captured_at >= TIMESTAMPTZ '{head["received"]}' - make_interval(days => {head["window"]})
          AND cl.captured_at <= TIMESTAMPTZ '{head["received"]}'
        """,
    )
    with path.open("w") as fh:
        for r in rows:
            r["minhash"] = [_u32(x) for x in r["minhash"]]
            fh.write(json.dumps(r) + "\n")
    return len(rows)


def _export_keys(cluster: Cluster, directory: Path) -> None:
    """The fingerprint key Secret, laid out as the services mount it (one base64 file per generation)."""
    name = f"{cluster.fullname}-fingerprint-key"
    data = json.loads(cluster.kubectl("get", "secret", name, "-o", "json"))["data"]
    directory.mkdir(mode=0o700)
    for k, v in data.items():
        if k.isdigit() or k == "active":
            p = directory / k
            p.write_bytes(base64.b64decode(v))
            p.chmod(0o600)


def test_cli_matches_the_pr_check(cluster: Cluster, workdir: Path) -> None:
    repo = os.environ["GCA_E2E_REPO"]
    head = _json(
        cluster,
        f"""
        SELECT row_to_json(x) FROM (
            SELECT h.id, h.head_sha AS head, h.base_sha AS base, h.event_received_at AS received, c.pr_number AS pr,
                   (SELECT matching_window_days FROM portal_settings) AS window,
                   (SELECT exclusion_rules FROM portal_settings) AS rules
            FROM change_head h JOIN change c ON c.id = h.change_id JOIN repository r ON r.id = c.repository_id
            WHERE r.full_name = '{repo}' AND h.status = 'complete'
              AND EXISTS (SELECT 1 FROM line_result l WHERE l.change_head_id = h.id AND l.outcome = 'ai_unmodified')
            ORDER BY h.completed_at DESC LIMIT 1) x
        """,
    )
    if head is None:
        pytest.skip(f"no attributed PR head with AI lines in {repo}; run `gca demo run` first")
    stored = {
        (r["p"], r["n"]): (r["o"], r["t"], r["g"])
        for r in _json(
            cluster,
            "SELECT coalesce(json_agg(json_build_object('p', file_path, 'n', line_no, 'o', outcome, 't', tier, "
            f"'g', credited_github_id)), '[]') FROM line_result WHERE change_head_id = '{head['id']}'",
        )
    }
    captures = workdir / "captures.jsonl"
    assert _export_captures(cluster, head, captures) > 0
    _export_keys(cluster, workdir / "keys")
    clone = workdir / "repo"
    subprocess.run(["gh", "repo", "clone", repo, str(clone), "--", "-q"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(clone), "fetch", "-q", "origin", f"pull/{head['pr']}/head", head["base"]],
        check=True,
        capture_output=True,
    )
    cmd = ["uv", "run", "gca", "--json", "attribute", "--repo", str(clone), "--base", head["base"],
           "--head", head["head"], "--captures", str(captures), "--key-file", str(workdir / "keys")]  # fmt: skip
    for rule in head["rules"]:
        cmd += ["--exclude", rule]
    out = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True).stdout
    report = json.loads(out)
    got = {
        (r["file_path"], r["line_no"]): (r["outcome"], r["tier"], r["credited_github_id"])
        for r in report["lines"]
    }
    assert got.keys() == stored.keys(), (
        sorted(got.keys() - stored.keys())[:5],
        sorted(stored.keys() - got.keys())[:5],
    )
    diff = {k: (stored[k], got[k]) for k in stored if stored[k] != got[k]}
    assert not diff, f"{len(diff)} lines differ from the PR check: {dict(list(diff.items())[:5])}"
    print(
        f"PR #{head['pr']} {head['head'][:12]}: {len(got)} lines identical; summary {report['summary']['counts']}"
    )
