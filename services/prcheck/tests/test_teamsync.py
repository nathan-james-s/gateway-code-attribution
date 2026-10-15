"""Team sync (T082; FR-027): GitHub teams, members and maintainers, reconciled without deleting history."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_prcheck import teamsync, webhooks
from gca_prcheck.teamsync import TeamSnapshot, apply, close_deleted


def _gid() -> int:
    return 8_000_000 + uuid.uuid4().int % 1_000_000


class Org:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        tag = uuid.uuid4().hex[:6]
        self.tag = tag
        self.team_gid = _gid()
        self.slug = f"core-{tag}"
        self.gid = {n: _gid() for n in ("ann", "bea", "cy", "ghost")}
        self.dev: dict[str, uuid.UUID] = {}
        with engine.begin() as conn:
            for n, created in (("ann", 30), ("bea", 30), ("cy", 1)):  # ghost never signed in
                self.dev[n] = conn.execute(
                    text(
                        "INSERT INTO developer (id, github_id, github_login, created_at) "
                        "VALUES (gen_random_uuid(), :g, :l, :c) RETURNING id"
                    ),
                    {"g": self.gid[n], "l": f"{n}-{tag}", "c": datetime.now(UTC) - timedelta(days=created)},
                ).scalar_one()

    def snap(
        self, members: tuple[str, ...], maintainers: tuple[str, ...] = (), slug: str | None = None
    ) -> TeamSnapshot:
        return TeamSnapshot(
            self.team_gid,
            slug or self.slug,
            "Core",
            frozenset(self.gid[m] for m in members),
            frozenset(self.gid[m] for m in maintainers),
        )

    def sync(self, *snaps: TeamSnapshot) -> dict[str, int]:
        # complete=False: other tests' teams share this database, so deleted-team handling is tested on its own.
        with self.engine.begin() as conn:
            return apply(conn, list(snaps), complete=False)

    def rows(self) -> list[Any]:
        with self.engine.connect() as conn:
            return list(
                conn.execute(
                    text(
                        "SELECT d.github_login AS login, m.source::text AS source, m.override_action::text AS action, "
                        "m.valid_from, m.valid_to FROM team_membership m JOIN team t ON t.id = m.team_id "
                        "JOIN developer d ON d.id = m.developer_id WHERE t.github_team_id = :g "
                        "ORDER BY d.github_login, m.valid_from"
                    ),
                    {"g": self.team_gid},
                )
            )

    def current(self) -> set[str]:
        return {r.login.split("-")[0] for r in self.rows() if r.valid_to is None and r.source == "github"}

    def leads(self) -> set[str]:
        with self.engine.connect() as conn:
            return {
                r.login.split("-")[0]
                for r in conn.execute(
                    text(
                        "SELECT d.github_login AS login FROM team_lead l JOIN team t ON t.id = l.team_id "
                        "JOIN developer d ON d.id = l.developer_id WHERE t.github_team_id = :g"
                    ),
                    {"g": self.team_gid},
                )
            }


def test_first_sync_opens_members_from_when_they_signed_in(pg_engine: Engine) -> None:
    org = Org(pg_engine)
    stats = org.sync(org.snap(("ann", "bea", "ghost"), maintainers=("ann",)))
    assert stats["opened"] == 2  # ghost has never signed in, so is no member
    assert org.current() == {"ann", "bea"} and org.leads() == {"ann"}
    with pg_engine.connect() as conn:
        created = dict(
            conn.execute(
                text("SELECT id, created_at FROM developer WHERE id = ANY(:d)"), {"d": list(org.dev.values())}
            ).fetchall()
        )
    for r in org.rows():
        assert r.valid_from == created[org.dev[r.login.split("-")[0]]]  # history covers merges since sign-in


def test_resync_closes_departed_and_opens_new_without_deleting(pg_engine: Engine) -> None:
    org = Org(pg_engine)
    org.sync(org.snap(("ann", "bea"), maintainers=("ann",)))
    assert org.sync(org.snap(("ann", "bea"), maintainers=("ann",))) == {"teams": 1, "opened": 0, "closed": 0}
    before = datetime.now(UTC)
    stats = org.sync(org.snap(("ann", "cy"), maintainers=("cy",)))
    assert stats == {"teams": 1, "opened": 1, "closed": 1}
    rows = org.rows()
    bea = [r for r in rows if r.login.startswith("bea")]
    assert len(bea) == 1 and bea[0].valid_to is not None and bea[0].valid_to >= before - timedelta(seconds=5)
    assert org.current() == {"ann", "cy"} and org.leads() == {"cy"}
    # cy was known at the previous sync, so they joined the team since: from this sync.
    cy = next(r for r in rows if r.login.startswith("cy"))
    assert cy.valid_from >= before - timedelta(seconds=5)
    # A developer who signs in between syncs starts from their sign-in, so their merges since then count.
    with pg_engine.begin() as conn:
        org.gid["dan"] = _gid()
        dan_created = conn.execute(
            text(
                "INSERT INTO developer (id, github_id, github_login) VALUES (gen_random_uuid(), :g, :l) "
                "RETURNING created_at"
            ),
            {"g": org.gid["dan"], "l": f"dan-{org.tag}"},
        ).scalar_one()
    org.sync(org.snap(("ann", "cy", "dan")))
    dan = next(r for r in org.rows() if r.login.startswith("dan"))
    assert dan.valid_from == dan_created

    # bea rejoins: a new row from now, the closed one kept.
    org.sync(org.snap(("ann", "bea", "cy")))
    bea = [r for r in org.rows() if r.login.startswith("bea")]
    assert len(bea) == 2 and bea[0].valid_to is not None and bea[1].valid_to is None
    assert bea[1].valid_from >= bea[0].valid_to


def test_overrides_are_never_changed_by_sync(pg_engine: Engine) -> None:
    org = Org(pg_engine)
    org.sync(org.snap(("ann",)))
    with pg_engine.begin() as conn:
        team = conn.execute(
            text("SELECT id FROM team WHERE github_team_id = :g"), {"g": org.team_gid}
        ).scalar_one()
        for who, action in (("bea", "add"), ("ann", "remove")):
            conn.execute(
                text(
                    "INSERT INTO team_membership (id, team_id, developer_id, source, override_action, valid_from) "
                    "VALUES (gen_random_uuid(), :t, :d, 'override', CAST(:a AS override_action), now())"
                ),
                {"t": team, "d": org.dev[who], "a": action},
            )
    org.sync(org.snap(()))  # everyone left on GitHub
    overrides = [(r.login.split("-")[0], r.action, r.valid_to) for r in org.rows() if r.source == "override"]
    assert sorted(overrides) == [("ann", "remove", None), ("bea", "add", None)]


def test_renamed_team_keeps_its_row_and_a_slug_clash_is_skipped(pg_engine: Engine) -> None:
    org = Org(pg_engine)
    org.sync(org.snap(("ann",)))
    org.sync(org.snap(("ann",), slug=f"renamed-{org.tag}"))
    with pg_engine.begin() as conn:
        assert conn.execute(
            text("SELECT slug FROM team WHERE github_team_id = :g"), {"g": org.team_gid}
        ).scalar() == (f"renamed-{org.tag}")
        conn.execute(
            text(
                "INSERT INTO team (id, slug, name, source) VALUES (gen_random_uuid(), :s, 'Mine', 'manual')"
            ),
            {"s": f"clash-{org.tag}"},
        )
    stats = org.sync(TeamSnapshot(_gid(), f"clash-{org.tag}", "Theirs", frozenset(), frozenset()))
    assert stats["teams"] == 0  # the in-stack team keeps the slug


def test_team_deleted_on_github_loses_members_but_keeps_history(pg_engine: Engine) -> None:
    org = Org(pg_engine)
    org.sync(org.snap(("ann", "bea"), maintainers=("ann",)))
    with pg_engine.begin() as conn:
        others = list(
            conn.execute(
                text("SELECT github_team_id FROM team WHERE source = 'github' AND github_team_id <> :g"),
                {"g": org.team_gid},
            ).scalars()
        )
        now = conn.execute(text("SELECT now()")).scalar_one()
        assert close_deleted(conn, others, now) == 2  # every other team is still on GitHub
    assert org.current() == set() and org.leads() == set()
    assert len(org.rows()) == 2  # closed, not deleted


class FakeApp:
    def __init__(
        self, org: str, teams: list[dict[str, Any]], members: dict[tuple[str, str], list[int]]
    ) -> None:
        self.org, self.teams, self.members = org, teams, members

    async def list_installations(self) -> list[dict[str, Any]]:
        return [{"id": 1, "account": {"login": "someone-else"}}, {"id": 2, "account": {"login": self.org}}]

    async def org_teams(self, inst: int, org: str) -> list[dict[str, Any]]:
        assert inst == 2
        return self.teams

    async def team_members(self, inst: int, org: str, slug: str, role: str) -> list[dict[str, Any]]:
        return [{"id": i} for i in self.members.get((slug, role), [])]


def test_fetch_reads_the_org_installation() -> None:
    gh = FakeApp(
        "Acme",
        [{"id": 5, "slug": "web", "name": "Web"}],
        {("web", "all"): [1, 2, 3], ("web", "maintainer"): [1]},
    )
    snaps = asyncio.run(teamsync.fetch(gh, "acme"))
    assert snaps == [TeamSnapshot(5, "web", "Web", frozenset({1, 2, 3}), frozenset({1}))]
    assert asyncio.run(teamsync.fetch(gh, "other-org")) is None


def _signed(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_team_webhooks_request_a_sync(pg_engine: Engine) -> None:
    requested: list[str] = []
    app = FastAPI()
    app.include_router(
        webhooks.create_router(pg_engine, object(), "s3cret", on_team_event=lambda: requested.append("sync"))  # type: ignore[arg-type]
    )
    c = TestClient(app)
    for event in ("membership", "team", "organization"):
        body = json.dumps({"action": "added", "installation": {"id": 2}}).encode()
        r = c.post(
            "/webhooks/github",
            content=body,
            headers={
                "x-hub-signature-256": _signed("s3cret", body),
                "x-github-delivery": str(uuid.uuid4()),
                "x-github-event": event,
            },
        )
        assert r.status_code == 202
    assert requested == ["sync", "sync", "sync"]
