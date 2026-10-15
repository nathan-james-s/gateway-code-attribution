"""Polling delivery for local installs (T052; contracts/github-app.md "Delivery modes").

Every poll lists open PRs in each installed repository and records any head SHA not seen before. Recording is
idempotent on (change_id, head_sha), so webhook delivery (US2) can share `record_head`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core.github import AppClient

from . import checkrun

log = logging.getLogger("gca.prcheck.polling")

_UPSERT_REPO = text("""
    INSERT INTO repository (id, github_id, full_name, installation_id, active, added_at)
    VALUES (gen_random_uuid(), :gid, :fn, :inst, true, now())
    ON CONFLICT (github_id) DO UPDATE
      SET full_name = EXCLUDED.full_name, installation_id = EXCLUDED.installation_id, active = true
    RETURNING id
""")
_UPSERT_CHANGE = text("""
    INSERT INTO change (id, repository_id, pr_number, opened_by_github_id, state)
    VALUES (gen_random_uuid(), :repo, :pr, :opener, 'open')
    ON CONFLICT (repository_id, pr_number) DO UPDATE SET state = change.state
    RETURNING id
""")
_INSERT_HEAD = text("""
    INSERT INTO change_head (id, change_id, head_sha, base_sha, event_received_at, status, coverage_status,
                             coverage_reasons, key_gens, counts, excluded_paths, is_final, attempts)
    VALUES (gen_random_uuid(), :change, :sha, :base, now(), 'pending', 'pending', '{}', '{}', '{}', '[]',
            false, 0)
    ON CONFLICT (change_id, head_sha) DO NOTHING
    RETURNING id
""")


def upsert_repository(engine: Engine, repo: dict[str, Any], installation_id: int) -> uuid.UUID:
    with engine.begin() as conn:
        return conn.execute(
            _UPSERT_REPO, {"gid": repo["id"], "fn": repo["full_name"], "inst": installation_id}
        ).scalar_one()


def record_head(engine: Engine, repository_id: uuid.UUID, pr: dict[str, Any]) -> uuid.UUID | None:
    """Create Change and ChangeHead for a PR head. Returns the new head id, or None if it was already known."""
    with engine.begin() as conn:
        change_id = conn.execute(
            _UPSERT_CHANGE, {"repo": repository_id, "pr": pr["number"], "opener": pr["user"]["id"]}
        ).scalar_one()
        return conn.execute(
            _INSERT_HEAD, {"change": change_id, "sha": pr["head"]["sha"], "base": pr["base"]["sha"]}
        ).scalar()


async def announce(
    engine: Engine, gh: AppClient, head_id: uuid.UUID, installation_id: int, full_name: str, head_sha: str
) -> None:
    """Show the check as in progress ("Waiting for capture to catch up") as soon as the head is known."""
    owner, repo = full_name.split("/", 1)
    try:
        run_id = await checkrun.start(gh, installation_id, owner, repo, head_sha)
    except Exception:
        log.exception("could not create check run for %s@%s", full_name, head_sha[:12])
        return
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE change_head SET check_run_id = :r WHERE id = :h"), {"r": run_id, "h": head_id}
        )


async def poll_once(engine: Engine, gh: AppClient) -> int:
    new_heads = 0
    for inst in await gh.list_installations():
        inst_id = int(inst["id"])
        try:
            repos = await gh.installation_repositories(inst_id)
        except Exception:
            log.exception("listing repositories failed for installation %s", inst_id)
            continue
        for repo in repos:
            try:
                repo_id = upsert_repository(engine, repo, inst_id)
                owner, name = repo["full_name"].split("/", 1)
                for pr in await gh.open_pulls(inst_id, owner, name):
                    head_id = record_head(engine, repo_id, pr)
                    if head_id is not None:
                        new_heads += 1
                        await announce(engine, gh, head_id, inst_id, repo["full_name"], pr["head"]["sha"])
            except Exception:
                log.exception("polling %s failed", repo.get("full_name"))
    return new_heads


async def run(engine: Engine, gh: AppClient, interval: float) -> None:
    while True:
        try:
            n = await poll_once(engine, gh)
            if n:
                log.info("recorded %d new PR heads", n)
        except Exception:
            log.exception("poll failed")
        await asyncio.sleep(interval)
