"""End-to-end harness (T065): install the demo, issue a credential, run `gca demo run`, wait for the check.

Talks to a real cluster and a real GitHub repository. Opt in with GCA_E2E=1; it reinstalls the demo release,
clears captured fingerprints between gateways and opens (then closes) PRs in GCA_E2E_REPO.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tests.privacy.scan import Cluster

ROOT = Path(__file__).resolve().parents[2]
GATEWAY_URL = "http://localhost:4000"
CHECK_NAME = "AI code attribution"


def run(
    cmd: list[str], *, env: dict[str, str] | None = None, timeout: float = 1800, log: Path | None = None
) -> str:
    res = subprocess.run(
        cmd, cwd=ROOT, env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=timeout
    )
    if log is not None:
        log.write_text(res.stdout + res.stderr)
    if res.returncode != 0:
        tail = (res.stdout + res.stderr)[-1500:]
        raise RuntimeError(f"{' '.join(cmd[:4])} failed ({res.returncode}):\n{tail}")
    return res.stdout


def github_files(workdir: Path) -> tuple[Path, Path]:
    """values-github.yaml and the App Secret: from GCA_E2E_APP (CI) or the files `gca setup github-app` wrote."""
    app = os.environ.get("GCA_E2E_APP")
    if not app:
        values, secret = ROOT / "values-github.yaml", ROOT / "github-app.secret.yaml"
        if not (values.exists() and secret.exists()):
            raise RuntimeError("set GCA_E2E_APP or run `uv run gca setup github-app` first")
        return values, secret
    data = json.loads(app)
    secret = workdir / "github-app.secret.yaml"
    values = workdir / "values-github.yaml"
    secret.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "gca-github-app"},
                "type": "Opaque",
                "stringData": {
                    "appId": str(data["appId"]),
                    "clientId": data["clientId"],
                    "clientSecret": data["clientSecret"],
                    "privateKey": data["privateKey"],
                    "webhookSecret": secrets.token_urlsafe(32),
                },
            }
        )
    )
    values.write_text(
        yaml.safe_dump({"github": {"existingSecret": "gca-github-app", "org": data.get("org", "")}})
    )
    secret.chmod(0o600)
    return values, secret


def wait_for_key(key: str, timeout: float = 300) -> None:
    body = json.dumps({"model": "demo-openai", "messages": [{"role": "user", "content": "ping"}]}).encode()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        req = urllib.request.Request(
            f"{GATEWAY_URL}/v1/chat/completions",
            data=body,
            method="POST",
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(5)
    raise TimeoutError("the gateway did not accept the new credential")


def wait_for_check(repo: str, sha: str, timeout: float = 900) -> dict[str, Any]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        runs = json.loads(run(["gh", "api", f"repos/{repo}/commits/{sha}/check-runs"]))["check_runs"]
        for cr in runs:
            if cr["name"] == CHECK_NAME and cr["status"] == "completed":
                return dict(cr)
        time.sleep(10)
    raise TimeoutError(f"no completed '{CHECK_NAME}' check on {sha[:12]}")


@dataclass
class DemoRun:
    gateway: str
    pr: int
    head_sha: str
    elapsed_s: float
    check: dict[str, Any]
    counts: dict[str, int]
    coverage: str
    summary_rows: int
    lines: dict[tuple[str, int], tuple[str, str]] = field(default_factory=dict)


def demo_run(
    cluster: Cluster,
    gateway: str,
    repo: str,
    values: Path,
    secret: Path,
    *,
    clear_captures: bool,
    logdir: Path,
) -> DemoRun:
    start = time.monotonic()
    run(
        ["make", "demo", f"GATEWAY={gateway}", f"VALUES={values}", f"SECRET={secret}"],
        timeout=2400,
        log=logdir / f"make-demo-{gateway}.log",
    )
    if clear_captures:
        # Each gateway's PR may only match its own gateway's captures; otherwise identical demo code would
        # match the previous run's fingerprints and the parity check would prove nothing.
        cluster.psql("TRUNCATE captured_line, lsh_band, capture_event")
    user = json.loads(run(["gh", "api", "user"]))
    key = (
        cluster.kubectl(
            "exec",
            f"deploy/{cluster.fullname}-portal",
            "--",
            "python",
            "-m",
            "gca_portal.admin_cli",
            "issue-credential",
            "--github-id",
            str(user["id"]),
            "--github-login",
            user["login"],
        )
        .decode()
        .strip()
        .splitlines()[-1]
    )
    wait_for_key(key)
    out = run(
        ["uv", "run", "gca", "demo", "run", "--repo", repo, "--gateway", gateway],
        env={"GCA_CREDENTIAL": key},
        timeout=900,
    )
    m = re.search(r"Opened https://github\.com/[^\s]+/pull/(\d+)", out)
    if not m:
        raise RuntimeError(f"gca demo run did not open a PR:\n{out[-800:]}")
    pr = int(m.group(1))
    sha = run(
        ["gh", "pr", "view", str(pr), "--repo", repo, "--json", "headRefOid", "-q", ".headRefOid"]
    ).strip()
    check = wait_for_check(repo, sha)
    elapsed = time.monotonic() - start
    head = json.loads(
        cluster.psql(
            "SELECT json_build_object('counts', h.counts, 'coverage', h.coverage_status) FROM change_head h "
            "JOIN change c ON c.id = h.change_id JOIN repository r ON r.id = c.repository_id "
            f"WHERE r.full_name = '{repo}' AND c.pr_number = {pr} AND h.head_sha = '{sha}'"
        )
    )
    rows = int(
        cluster.psql(
            f"SELECT count(*) FROM v_change_summary WHERE repository = '{repo}' AND pr_number = {pr}"
        )
    )
    lines = {}
    for ln in cluster.psql(
        "SELECT l.file_path || '|' || l.line_no || '|' || l.outcome || '|' || l.tier FROM line_result l "
        "JOIN change_head h ON h.id = l.change_head_id JOIN change c ON c.id = h.change_id "
        f"JOIN repository r ON r.id = c.repository_id WHERE r.full_name = '{repo}' AND c.pr_number = {pr}"
    ).splitlines():
        path, no, outcome, tier = ln.split("|")
        lines[(path, int(no))] = (outcome, tier)
    return DemoRun(gateway, pr, sha, elapsed, check, head["counts"], head["coverage"], rows, lines)


def close_pr(repo: str, pr: int) -> None:
    subprocess.run(
        ["gh", "pr", "close", str(pr), "--repo", repo, "--delete-branch"],
        cwd=ROOT,
        capture_output=True,
        timeout=120,
    )


def workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="gca-e2e-"))
