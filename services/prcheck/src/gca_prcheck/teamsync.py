"""Team sync (T082; FR-027; data-model.md Team, TeamMembership, TeamLead).

Teams, members and maintainers come from the GitHub organization's teams. A sync runs on the App's `membership`,
`team` and `organization` webhook events, within a minute of a new developer signing in to the portal, and as a
full resync every six hours. It runs here rather than in the portal because this service already holds the App's
key; the portal only ever acts with the signed-in user's token.

- Team (`source=github`) is upserted for every GitHub team.
- TeamMembership (`source=github`) is reconciled without deleting anything: departed members' rows are closed
  (`valid_to=now()`) and new members' rows are opened. A developer the stack didn't know at the team's previous
  sync starts from when they first signed in, so "membership as of the merge date" covers what they merged since.
- TeamLead (`source=github_maintainer`) mirrors the current maintainers.
- Override rows (`source=override`) are never changed.

Only accounts that have signed in to the portal (a Developer row) can be members. Sync never creates developers:
an account without one is unmapped, and its lines are not observed (FR-015).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

__all__ = ["TeamSnapshot", "TeamSync", "apply", "close_deleted", "fetch", "sync_org"]

log = logging.getLogger("gca.prcheck.teamsync")

FULL_RESYNC_SECONDS = 6 * 3600
CHECK_SECONDS = 60.0
EVENTS = {"membership", "team", "organization"}


@dataclass(frozen=True)
class TeamSnapshot:
    github_team_id: int
    slug: str
    name: str
    members: frozenset[int]  # GitHub account ids
    maintainers: frozenset[int]


async def _installation_for(gh: Any, org: str) -> int | None:
    for inst in await gh.list_installations():
        account = inst.get("account") or {}
        if str(account.get("login", "")).lower() == org.lower():
            return int(inst["id"])
    return None


async def fetch(gh: Any, org: str) -> list[TeamSnapshot] | None:
    """The organization's teams as GitHub has them now, or None if the App isn't installed on ``org``."""
    inst = await _installation_for(gh, org)
    if inst is None:
        return None
    out = []
    for t in await gh.org_teams(inst, org):
        members = await gh.team_members(inst, org, t["slug"], "all")
        maintainers = await gh.team_members(inst, org, t["slug"], "maintainer")
        out.append(
            TeamSnapshot(
                int(t["id"]),
                t["slug"],
                t["name"],
                frozenset(int(m["id"]) for m in members),
                frozenset(int(m["id"]) for m in maintainers),
            )
        )
    return out


def _upsert_team(conn: Connection, snap: TeamSnapshot) -> tuple[uuid.UUID, datetime | None] | None:
    try:
        with conn.begin_nested():
            row = conn.execute(
                text(
                    "INSERT INTO team (id, github_team_id, slug, name, source) "
                    "VALUES (gen_random_uuid(), :g, :slug, :name, 'github') "
                    "ON CONFLICT (github_team_id) DO UPDATE SET slug = EXCLUDED.slug, name = EXCLUDED.name "
                    "RETURNING id, synced_at"
                ),
                {"g": snap.github_team_id, "slug": snap.slug, "name": snap.name},
            ).one()
    except IntegrityError:
        # The slug belongs to a team an admin defined in the stack; that team wins.
        log.warning("GitHub team %r skipped: an in-stack team already uses that slug", snap.slug)
        return None
    return row.id, row.synced_at


def _reconcile_members(
    conn: Connection,
    team_id: uuid.UUID,
    previous_sync: datetime | None,
    want: dict[uuid.UUID, datetime],
    now: datetime,
) -> tuple[int, int]:
    open_rows = conn.execute(
        text(
            "SELECT id, developer_id FROM team_membership "
            "WHERE team_id = :t AND source = 'github' AND valid_to IS NULL"
        ),
        {"t": team_id},
    ).fetchall()
    have = {r.developer_id for r in open_rows}
    gone = [r.id for r in open_rows if r.developer_id not in want]
    if gone:
        conn.execute(
            text(
                "UPDATE team_membership SET valid_to = greatest(:now, valid_from + interval '1 microsecond') "
                "WHERE id = ANY(:ids)"
            ),
            {"now": now, "ids": gone},
        )
    opened = 0
    for dev_id, created_at in want.items():
        if dev_id in have:
            continue
        if previous_sync is not None and created_at <= previous_sync:
            start = now  # the stack knew this developer last time: they joined the team since
        else:
            last_closed = conn.execute(
                text(
                    "SELECT max(valid_to) FROM team_membership "
                    "WHERE team_id = :t AND developer_id = :d AND source = 'github'"
                ),
                {"t": team_id, "d": dev_id},
            ).scalar()
            start = max(created_at, last_closed) if last_closed else created_at
        conn.execute(
            text(
                "INSERT INTO team_membership (id, team_id, developer_id, source, valid_from) "
                "VALUES (gen_random_uuid(), :t, :d, 'github', :f)"
            ),
            {"t": team_id, "d": dev_id, "f": min(start, now)},
        )
        opened += 1
    return opened, len(gone)


def _reconcile_leads(conn: Connection, team_id: uuid.UUID, want: set[uuid.UUID]) -> None:
    conn.execute(
        text(
            "DELETE FROM team_lead WHERE team_id = :t AND source = 'github_maintainer' "
            "AND NOT (developer_id = ANY(:want))"
        ),
        {"t": team_id, "want": list(want)},
    )
    for dev_id in want:
        conn.execute(
            text(
                "INSERT INTO team_lead (id, team_id, developer_id, source) "
                "VALUES (gen_random_uuid(), :t, :d, 'github_maintainer') "
                "ON CONFLICT (team_id, developer_id, source) DO NOTHING"
            ),
            {"t": team_id, "d": dev_id},
        )


def apply(conn: Connection, snapshots: list[TeamSnapshot], *, complete: bool = True) -> dict[str, int]:
    """Make the stack's GitHub-sourced team rows match ``snapshots``. Idempotent.

    ``complete``: the snapshots are every team in the organization, so a GitHub team missing from them was deleted.
    """
    now = conn.execute(text("SELECT now()")).scalar_one()
    devs = {
        r.github_id: (r.id, r.created_at)
        for r in conn.execute(text("SELECT id, github_id, created_at FROM developer"))
    }
    stats = {"teams": 0, "opened": 0, "closed": 0}
    for snap in snapshots:
        upserted = _upsert_team(conn, snap)
        if upserted is None:
            continue
        team_id, previous_sync = upserted
        want = {devs[g][0]: devs[g][1] for g in snap.members if g in devs}
        opened, closed = _reconcile_members(conn, team_id, previous_sync, want, now)
        _reconcile_leads(conn, team_id, {devs[g][0] for g in snap.maintainers if g in devs})
        conn.execute(text("UPDATE team SET synced_at = :now WHERE id = :t"), {"now": now, "t": team_id})
        stats["teams"] += 1
        stats["opened"] += opened
        stats["closed"] += closed
    if complete:
        stats["closed"] += close_deleted(conn, [s.github_team_id for s in snapshots], now)
    return stats


def close_deleted(conn: Connection, seen: list[int], now: datetime) -> int:
    """Teams deleted on GitHub keep their row (history) but lose their GitHub members and maintainers."""
    gone = conn.execute(
        text(
            "SELECT id FROM team WHERE source = 'github' AND github_team_id IS NOT NULL "
            "AND NOT (github_team_id = ANY(:seen))"
        ),
        {"seen": seen},
    ).fetchall()
    closed = 0
    for row in gone:
        closed += _reconcile_members(conn, row.id, now, {}, now)[1]
        _reconcile_leads(conn, row.id, set())
    return closed


async def sync_org(engine: Engine, gh: Any, org: str) -> dict[str, int] | None:
    snapshots = await fetch(gh, org)
    if snapshots is None:
        log.warning("team sync skipped: the GitHub App isn't installed on organization %r", org)
        return None
    with engine.begin() as conn:
        stats = apply(conn, snapshots)
    log.info("team sync: %(teams)d teams, %(opened)d memberships opened, %(closed)d closed", stats)
    return stats


@dataclass
class TeamSync:
    """Runs `sync_org` on request (webhooks), when a developer is new, and every FULL_RESYNC_SECONDS."""

    engine: Engine
    gh: Any
    org: str
    full_seconds: float = FULL_RESYNC_SECONDS
    check_seconds: float = CHECK_SECONDS
    requested: asyncio.Event = field(default_factory=asyncio.Event)

    def request(self) -> None:
        self.requested.set()

    def _newest_developer(self) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT count(*), max(created_at) FROM developer")).one()

    async def run(self) -> None:
        last_full = float("-inf")
        known: Any = None
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.requested.wait(), timeout=self.check_seconds)
            try:
                newest = await asyncio.to_thread(self._newest_developer)
                due = (
                    self.requested.is_set()
                    or time.monotonic() - last_full >= self.full_seconds
                    or newest != known
                )
                if due:
                    self.requested.clear()
                    await sync_org(self.engine, self.gh, self.org)
                    last_full, known = time.monotonic(), newest
            except Exception as exc:
                log.warning("team sync failed, retrying: %s", type(exc).__name__)
