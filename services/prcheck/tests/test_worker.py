"""T052-T054 end to end against PostgreSQL with a fake GitHub: poll, gate on the watermark, attribute, report."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core import messages
from gca_core.github import BlameRange, ChangedFile, Comparison, PrCommit
from gca_core.keys import KeyRing
from gca_ingest.store import handle
from gca_prcheck import polling, worker
from gca_prcheck.config import PrcheckConfig
from gcattr import CapturedToolOutput, FingerprintKey, extract

SECRET = b"\x42" * 32
KEY = FingerprintKey(1, SECRET)
CAPTURED = "def total(items):\n    return sum(item.price * item.quantity for item in items if item.active)\n"
# Line 1 exact, line 2 edited (anchored), line 3 human, line 4 trivial, line 5 by an unmapped author.
PR_FILE = [
    "def total(items):",
    "    return sum(item.price * item.quantity for item in items if item.enabled)",
    "    print('a line the developer typed themselves, with no AI involved')",
    "",
    "    log_everything_to_a_remote_audit_service(items, verbose=True)",
]


class FakeGitHub:
    def __init__(self, repo_gid: int, full_name: str, author: int, other: int) -> None:
        self.repo = {"id": repo_gid, "full_name": full_name}
        self.author, self.other = author, other
        self.created: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.pr = {"number": 7, "user": {"id": author}, "head": {"sha": "h" * 40}, "base": {"sha": "b" * 40}}

    async def list_installations(self) -> list[dict[str, Any]]:
        return [{"id": 11}]

    async def installation_repositories(self, inst: int) -> list[dict[str, Any]]:
        return [self.repo]

    async def open_pulls(self, inst: int, owner: str, repo: str) -> list[dict[str, Any]]:
        return [self.pr]

    async def compare(self, inst: int, owner: str, repo: str, base: str, head: str) -> Comparison:
        patch = "@@ -0,0 +1,5 @@\n" + "\n".join("+" + ln for ln in PR_FILE)
        files = [
            ChangedFile("src/app.py", "added", 5, patch, None),
            ChangedFile("assets/logo.png", "added", 0, None, None),
        ]
        return Comparison("m" * 40, files, ["c1", "c2"])

    async def pr_commits(self, inst: int, owner: str, repo: str, number: int) -> list[PrCommit]:
        return [PrCommit("c1", self.author), PrCommit("c2", self.other)]

    async def blame(self, inst: int, owner: str, repo: str, oid: str, path: str) -> list[BlameRange]:
        return [BlameRange(1, 4, "c1"), BlameRange(5, 5, "c2")]

    async def blob_text(self, inst: int, owner: str, repo: str, path: str, ref: str) -> str | None:
        return None  # the png is binary

    async def create_check_run(self, inst: int, owner: str, repo: str, **body: Any) -> int:
        self.created.append(body)
        return 555

    async def update_check_run(self, inst: int, owner: str, repo: str, run_id: int, **body: Any) -> None:
        self.updates.append(body)


@pytest.fixture
def keyring(tmp_path: Path) -> KeyRing:
    (tmp_path / "1").write_text(base64.b64encode(SECRET).decode())
    (tmp_path / "active").write_text("1")
    return KeyRing(tmp_path)


def _capture(conn: Any, gid: int) -> None:
    dev = conn.execute(
        text(
            "INSERT INTO developer (id, github_id, github_login) VALUES (gen_random_uuid(), :g, 'ada') RETURNING id"
        ),
        {"g": gid},
    ).scalar()
    cred = conn.execute(
        text(
            "INSERT INTO gateway_credential (id, developer_id, gateway_type, key_hash, status) "
            "VALUES (gen_random_uuid(), :d, 'agentgateway', :h, 'active') RETURNING id"
        ),
        {"d": dev, "h": "sha256:" + uuid.uuid4().hex * 2},
    ).scalar()
    out = CapturedToolOutput(
        "anthropic_messages",
        "Write",
        "json_args",
        {"file_path": "/work/src/app.py", "content": CAPTURED},
        True,
    )
    iid = str(uuid.uuid4())
    env = {
        "schema": "gca.capture.v1",
        "instance_id": iid,
        "seq": 0,
        "gateway_type": "agentgateway",
        "sent_at": datetime.now(UTC).isoformat(),
    }
    body = messages.event_body(
        api_format="anthropic_messages",
        model="m",
        received_at=datetime.now(UTC).isoformat(),
        status="captured",
        alg=1,
        key_gen=1,
        lines=extract(out, KEY, 1),
        tool_call_count=1,
        credential_id=str(cred),
    )
    handle(conn, messages.validate({**env, **body}))


def _heartbeat(conn: Any) -> None:
    conn.execute(text("UPDATE capture_instance SET status = 'stale' WHERE status = 'active'"))
    env = {
        "schema": "gca.capture.v1",
        "instance_id": str(uuid.uuid4()),
        "seq": 0,
        "gateway_type": "agentgateway",
        "sent_at": datetime.now(UTC).isoformat(),
    }
    handle(conn, messages.validate({**env, **messages.heartbeat_body(responses_seen=1, buffer_depth=0)}))


async def test_poll_gate_attribute_report(pg_engine: Engine, keyring: KeyRing) -> None:
    gid, other = 8_000_000 + uuid.uuid4().int % 1_000_000, 9_100_000 + uuid.uuid4().int % 1_000_000
    full_name = f"acme/repo{gid}"
    gh = FakeGitHub(gid, full_name, gid, other)
    with pg_engine.begin() as conn:
        _capture(conn, gid)
        conn.execute(text("UPDATE capture_instance SET status = 'stale' WHERE status = 'active'"))

    assert await polling.poll_once(pg_engine, gh) == 1  # type: ignore[arg-type]
    assert await polling.poll_once(pg_engine, gh) == 0  # idempotent on (change, head_sha)
    assert gh.created[0]["status"] == "in_progress" and gh.created[0]["output"]["title"].startswith("Waiting")

    # No active capture instance yet: the head waits (FR-017).
    assert worker.claim_ready(pg_engine) is None
    with pg_engine.begin() as conn:
        _heartbeat(conn)
    head_id = worker.claim_ready(pg_engine)
    assert head_id is not None

    cfg = PrcheckConfig(portal_url="http://portal")
    await worker.process_head(pg_engine, gh, keyring, cfg, head_id)  # type: ignore[arg-type]

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT line_no, outcome::text, tier::text, credited_github_id FROM line_result "
                "WHERE change_head_id = :h ORDER BY line_no"
            ),
            {"h": head_id},
        ).fetchall()
        head = conn.execute(
            text(
                "SELECT status::text, coverage_status::text, counts, excluded_paths, check_run_id "
                "FROM change_head WHERE id = :h"
            ),
            {"h": head_id},
        ).one()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        (1, "ai_unmodified", "exact"),
        (2, "ai_modified", "anchored"),
        (3, "human", "none"),
        (4, "indeterminate", "none"),
        (5, "not_observed", "none"),
    ]
    assert rows[4][3] == other  # unmapped account recorded, developer left empty
    assert head[0] == "complete" and head[1] == "complete" and head[4] == 555
    assert head[2]["excluded"] == 1 and head[3] == [{"path": "assets/logo.png", "reason": "binary"}]

    final = gh.updates[0]
    assert final["conclusion"] == "neutral" and final["status"] == "completed"
    assert final["output"]["title"] == "AI 67% · human 33% · indeterminate 1 lines · coverage: complete"
    assert f"http://portal/changes/{full_name}/7" in final["output"]["summary"]
    # No code anywhere in what goes to GitHub.
    sent = repr(gh.updates) + repr(gh.created)
    assert "item.price" not in sent and "print(" not in sent
