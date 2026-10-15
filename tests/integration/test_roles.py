"""T087: the viewer role matrix for per-developer views (FR-029, FR-029a; quickstart.md section 3).

Runs the portal against a migrated PostgreSQL with GitHub faked per viewer: who owns the organization and who
maintains which team. Checks that

- an org owner can view any developer;
- a team maintainer can view only their team's members;
- a plain member gets 403;
- a ViewerRoleGrant grant or revoke changes access at the next request;
- `per_developer_enabled=false` hides the views from everyone;
- GitHub-side changes apply once the 60-second role cache expires;

and that team totals equal the sum of member credits, in the portal and in Grafana's `v_team_daily`, with
membership taken as of the merge date.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_portal.app import create_app
from gca_portal.backends import ActiveKey
from gca_portal.config import PortalConfig

ORG = "acme"
FORBIDDEN = {"error": "forbidden", "message": "you can't view this"}


class FakeBackend:
    def issue(self, credential_id: str, github_id: int, key: str, key_hash: str) -> str | None:
        return None

    def revoke(self, credential_id: str, gateway_ref: str | None) -> None:
        return None

    def sync(self, active: list[ActiveKey]) -> None:
        return None

    def ensure(self) -> None:
        return None


class GitHubOrg:
    """Who owns the organization and who maintains which team, as GitHub would answer each viewer."""

    def __init__(self) -> None:
        self.owners: set[str] = set()
        self.maintainers: dict[str, set[str]] = {}

    def user(self, gid: int, login: str) -> FakeUser:
        return FakeUser(self, gid, login)


class FakeUser:
    def __init__(self, org: GitHubOrg, gid: int, login: str) -> None:
        self.org, self.gid, self.login, self.token = org, gid, login, f"tok-{login}"
        self.calls = 0

    async def me(self) -> dict[str, Any]:
        return {"id": self.gid, "login": self.login}

    async def org_role(self, org: str) -> str | None:
        self.calls += 1
        return "admin" if self.login in self.org.owners else "member"

    async def maintained_teams(self, org: str, login: str) -> list[str]:
        return sorted(self.org.maintainers.get(login, set()))

    async def user_by_login(self, login: str) -> dict[str, Any] | None:
        return None

    async def can_view_repo(self, owner: str, repo: str) -> bool:
        return True


def _gid() -> int:
    return 7_000_000 + uuid.uuid4().int % 1_000_000


class World:
    """Two GitHub teams. alpha: alice, bob (maintained by mia). beta: carol, bob (maintained by ben)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.github = GitHubOrg()
        tag = uuid.uuid4().hex[:6]
        self.alpha, self.beta = f"alpha-{tag}", f"beta-{tag}"
        names = ("owner", "mia", "ben", "plain", "alice", "bob", "carol", "dave")
        self.login = {n: f"{n}-{tag}" for n in names}
        self.gid = {n: _gid() for n in names}
        self.dev: dict[str, uuid.UUID] = {}
        self.team: dict[str, uuid.UUID] = {}
        long_ago = datetime.now(UTC) - timedelta(days=60)
        with engine.begin() as conn:
            for n in names:
                self.dev[n] = conn.execute(
                    text(
                        "INSERT INTO developer (id, github_id, github_login, created_at) "
                        "VALUES (gen_random_uuid(), :g, :l, :c) RETURNING id"
                    ),
                    {"g": self.gid[n], "l": self.login[n], "c": long_ago},
                ).scalar_one()
            for slug in (self.alpha, self.beta):
                self.team[slug] = conn.execute(
                    text(
                        "INSERT INTO team (id, github_team_id, slug, name, source, synced_at) "
                        "VALUES (gen_random_uuid(), :g, :s, :s, 'github', now()) RETURNING id"
                    ),
                    {"g": _gid(), "s": slug},
                ).scalar_one()
            for slug, members in (
                (self.alpha, ("alice", "bob", "mia")),
                (self.beta, ("carol", "bob", "ben")),
            ):
                for m in members:
                    self.member(conn, slug, m, long_ago)
        self.github.owners.add(self.login["owner"])
        self.github.maintainers[self.login["mia"]] = {self.alpha}
        self.github.maintainers[self.login["ben"]] = {self.beta}

    def member(
        self,
        conn: Any,
        slug: str,
        who: str,
        start: datetime,
        end: datetime | None = None,
        source: str = "github",
        action: str | None = None,
    ) -> None:
        conn.execute(
            text(
                "INSERT INTO team_membership (id, team_id, developer_id, source, override_action, valid_from, "
                "valid_to) VALUES (gen_random_uuid(), :t, :d, CAST(:s AS membership_source), "
                "CAST(:a AS override_action), :f, :to)"
            ),
            {"t": self.team[slug], "d": self.dev[who], "s": source, "a": action, "f": start, "to": end},
        )

    def client(self, who: str) -> TestClient:
        user = self.github.user(self.gid[who], self.login[who])

        async def exchange(*args: Any) -> FakeUser:
            return user

        cfg = PortalConfig(github_client_id="cid", github_org=ORG)
        app = create_app(self.engine, cfg, FakeBackend(), exchange=exchange, user_client=lambda tok: user)
        c = TestClient(app)
        r = c.get("/auth/login", follow_redirects=False)
        state = re.search(r"state=([^&]+)", r.headers["location"]).group(1)  # type: ignore[union-attr]
        c.get(f"/auth/callback?code=x&state={state}", follow_redirects=False)
        c.app_state = app.state  # type: ignore[attr-defined]
        return c

    def can_view(self, c: TestClient, who: str) -> int:
        return c.get(f"/api/developers/{self.login[who]}").status_code

    def can_view_team(self, c: TestClient, slug: str) -> int:
        return c.get(f"/api/teams/{slug}/developers").status_code


@pytest.fixture
def world(pg_engine: Engine) -> Iterator[World]:
    with pg_engine.connect() as conn:
        saved = conn.execute(
            text("SELECT per_developer_enabled, visible_roles FROM portal_settings WHERE id = 1")
        ).one()
    yield World(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(
            text("UPDATE portal_settings SET per_developer_enabled = :e, visible_roles = :r WHERE id = 1"),
            {"e": saved.per_developer_enabled, "r": list(saved.visible_roles)},
        )


def test_org_owner_views_any_developer(world: World) -> None:
    owner = world.client("owner")
    assert owner.get("/api/me").json()["roles"] == ["admin"]
    for who in ("alice", "bob", "carol", "dave", "plain"):
        assert world.can_view(owner, who) == 200
    assert world.can_view_team(owner, world.alpha) == 200
    assert world.can_view_team(owner, world.beta) == 200


def test_team_maintainer_views_only_their_members(world: World) -> None:
    mia = world.client("mia")
    me = mia.get("/api/me").json()
    assert me["roles"] == ["team_lead"] and me["lead_teams"] == [world.alpha]
    assert world.can_view(mia, "alice") == 200 and world.can_view(mia, "bob") == 200
    assert world.can_view(mia, "carol") == 403 and world.can_view(mia, "dave") == 403
    assert world.can_view_team(mia, world.alpha) == 200
    assert world.can_view_team(mia, world.beta) == 403
    # 403s don't reveal whether the developer or team exists.
    missing = mia.get("/api/developers/no-such-login-anywhere")
    other = mia.get(f"/api/developers/{world.login['carol']}")
    assert missing.status_code == other.status_code == 403 and missing.json() == other.json() == FORBIDDEN
    assert mia.get("/api/teams/no-such-team/developers").json() == FORBIDDEN
    assert mia.get("/admin").status_code == 403


def test_plain_member_is_forbidden(world: World) -> None:
    plain = world.client("plain")
    assert plain.get("/api/me").json()["roles"] == ["other"]
    for who in ("alice", "carol", "plain"):
        assert world.can_view(plain, who) == 403
    assert world.can_view_team(plain, world.alpha) == 403
    page = plain.get(f"/developers/{world.login['alice']}")
    assert page.status_code == 403 and page.json() == FORBIDDEN


def test_grants_and_revokes_apply_at_the_next_request(world: World) -> None:
    owner, plain, mia = world.client("owner"), world.client("plain"), world.client("mia")

    def role(body: dict[str, str]) -> Any:
        return owner.post("/api/admin/roles", json=body)

    # Grant plain the team-lead role for beta: their very next request sees beta's members.
    assert role(
        {"github_login": world.login["plain"], "role": "team_lead", "team": world.beta, "action": "grant"}
    ).json() == {"status": "grant"}
    assert world.can_view(plain, "carol") == 200 and world.can_view(plain, "alice") == 403
    assert world.can_view_team(plain, world.beta) == 200

    # Revoke mia's GitHub-derived lead role for alpha.
    assert world.can_view(mia, "alice") == 200
    role({"github_login": world.login["mia"], "role": "team_lead", "team": world.alpha, "action": "revoke"})
    assert world.can_view(mia, "alice") == 403 and world.can_view_team(mia, world.alpha) == 403
    # Clearing the override returns to the GitHub default.
    role({"github_login": world.login["mia"], "role": "team_lead", "team": world.alpha, "action": "clear"})
    assert world.can_view(mia, "alice") == 200

    # Admin grant and revoke.
    role({"github_login": world.login["plain"], "role": "admin", "action": "grant"})
    assert plain.get("/admin").status_code == 200 and world.can_view(plain, "dave") == 200
    role({"github_login": world.login["plain"], "role": "admin", "action": "revoke"})
    assert plain.get("/admin").status_code == 403 and world.can_view(plain, "dave") == 403

    # The org owner's GitHub admin role can be revoked too, but not by themselves.
    r = role({"github_login": world.login["owner"], "role": "admin", "action": "revoke"})
    assert r.status_code == 409 and r.json()["error"] == "conflict"
    bad = role({"github_login": world.login["plain"], "role": "team_lead", "action": "grant"})
    assert bad.status_code == 422
    listed = owner.get("/api/admin/roles").json()["grants"]
    assert {(g["github_login"], g["role"], g["action"]) for g in listed} >= {
        (world.login["plain"], "team_lead", "grant"),
        (world.login["plain"], "admin", "revoke"),
    }


def test_per_developer_views_off_hides_them_from_everyone(world: World) -> None:
    owner, mia = world.client("owner"), world.client("mia")
    r = owner.post("/api/admin/settings", json={"per_developer_enabled": False})
    assert r.status_code == 200 and r.json()["per_developer_enabled"] is False
    assert world.can_view(owner, "alice") == 403 and world.can_view_team(owner, world.alpha) == 403
    assert world.can_view(mia, "alice") == 403
    assert owner.get("/admin/settings").status_code == 200  # the setting itself stays reachable
    owner.post("/api/admin/settings", json={"per_developer_enabled": True})
    assert world.can_view(owner, "alice") == 200


def test_visible_roles_choose_who_sees_the_views(world: World) -> None:
    owner, mia, plain = world.client("owner"), world.client("mia"), world.client("plain")
    owner.post("/api/admin/settings", json={"visible_roles": ["admin"]})
    assert world.can_view(owner, "alice") == 200 and world.can_view(mia, "alice") == 403
    owner.post("/api/admin/settings", json={"visible_roles": ["admin", "team_lead", "other"]})
    assert world.can_view(plain, "carol") == 200
    assert owner.post("/api/admin/settings", json={"visible_roles": ["everyone"]}).status_code == 422


def test_github_side_changes_apply_within_60_seconds(world: World) -> None:
    clock = [1000.0]
    plain = world.client("plain")
    plain.app_state.access.cache.clock = lambda: clock[0]  # type: ignore[attr-defined]
    assert world.can_view_team(plain, world.alpha) == 403
    world.github.maintainers[world.login["plain"]] = {world.alpha}  # made a maintainer on GitHub
    clock[0] += 30
    assert world.can_view_team(plain, world.alpha) == 403  # still cached
    clock[0] += 31
    assert world.can_view_team(plain, world.alpha) == 200  # within 60 seconds
    world.github.owners.add(world.login["plain"])
    clock[0] += 61
    assert world.can_view(plain, "dave") == 200
    world.github.owners.discard(world.login["plain"])
    world.github.maintainers.pop(world.login["plain"])
    clock[0] += 61
    assert world.can_view(plain, "alice") == 403


# ----------------------------------------------------------------------------------------------- team totals
def _merged_change(
    world: World, merged_at: datetime, lines: list[tuple[str, str, str]], alg: int = 1
) -> None:
    """A merged change whose final head has the given (developer, outcome, tier) lines."""
    with world.engine.begin() as conn:
        repo = conn.execute(
            text(
                "INSERT INTO repository (id, github_id, full_name, installation_id, active) "
                "VALUES (gen_random_uuid(), :g, :fn, 1, true) RETURNING id"
            ),
            {"g": _gid(), "fn": f"acme/roles-{uuid.uuid4().hex[:8]}"},
        ).scalar_one()
        change = conn.execute(
            text(
                "INSERT INTO change (id, repository_id, pr_number, opened_by_github_id, state, merged_at) "
                "VALUES (gen_random_uuid(), :r, 1, 1, 'merged', :t) RETURNING id"
            ),
            {"r": repo, "t": merged_at},
        ).scalar_one()
        head = conn.execute(
            text(
                "INSERT INTO change_head (id, change_id, head_sha, event_received_at, status, coverage_status, "
                "coverage_reasons, key_gens, counts, excluded_paths, is_final, attempts, completed_at, alg) "
                "VALUES (gen_random_uuid(), :c, 'f00d', now(), 'complete', 'complete', '{}', '{1}', '{}', '[]', "
                "true, 1, now(), :alg) RETURNING id"
            ),
            {"c": change, "alg": alg},
        ).scalar_one()
        conn.execute(text("UPDATE change SET final_head_id = :h WHERE id = :c"), {"h": head, "c": change})
        for n, (who, outcome, tier) in enumerate(lines, start=1):
            confidence = {"anchored": "high", "broad": "lower"}.get(tier)
            matched = uuid.uuid4() if outcome.startswith("ai_") else None
            conn.execute(
                text(
                    "INSERT INTO line_result (change_head_id, file_path, line_no, outcome, tier, confidence, "
                    "similarity, credited_developer_id, credited_github_id, matched_capture_event_id) VALUES "
                    "(:h, 'src/x.py', :n, CAST(:o AS line_outcome), CAST(:t AS match_tier), "
                    "CAST(:conf AS match_confidence), :sim, :d, :g, :m)"
                ),
                {
                    "h": head,
                    "n": n,
                    "o": outcome,
                    "t": tier,
                    "conf": confidence,
                    "sim": 0.8 if confidence else None,
                    "d": world.dev[who],
                    "g": world.gid[who],
                    "m": matched,
                },
            )


def test_team_totals_equal_the_sum_of_member_credits(world: World) -> None:
    now = datetime.now(UTC)
    with world.engine.begin() as conn:
        # dave joined alpha 20 days ago and left 5 days ago; eve-like override: carol added to alpha by an admin.
        world.member(conn, world.alpha, "dave", now - timedelta(days=20), now - timedelta(days=5))
        world.member(conn, world.alpha, "carol", now - timedelta(days=60), source="override", action="add")
        # bob is removed from beta by an override (still a GitHub member).
        world.member(conn, world.beta, "bob", now - timedelta(days=60), source="override", action="remove")
    a, m, b, h, i = (
        ("ai_unmodified", "exact"),
        ("ai_modified", "anchored"),
        ("ai_modified", "broad"),
        ("human", "none"),
        ("indeterminate", "none"),
    )
    _merged_change(
        world,
        now - timedelta(days=10),
        [("alice", *a), ("alice", *b), ("bob", *m), ("bob", *h), ("dave", *a), ("carol", *b), ("carol", *i)],
    )
    _merged_change(world, now - timedelta(days=2), [("dave", *a), ("plain", *a), ("alice", *h)], alg=2)

    owner = world.client("owner")
    team = owner.get(f"/api/teams/{world.alpha}/developers").json()
    rows = {d["github_login"]: d for d in team["developers"]}
    login = world.login
    # dave counts on the 10-day-old merge (a member then) but not the 2-day-old one (he'd left).
    assert rows[login["dave"]]["ai_unmodified"] == 1 and rows[login["dave"]]["current_member"] is False
    assert rows[login["carol"]]["ai_modified_broad"] == 1  # admin-added member
    assert login["plain"] not in rows
    totals = team["totals"]
    for k in ("ai_unmodified", "ai_modified_anchored", "ai_modified_broad", "human", "indeterminate"):
        assert totals[k] == sum(d[k] for d in team["developers"]), k
    assert (totals["ai_unmodified"], totals["ai_modified_anchored"], totals["ai_modified_broad"]) == (2, 1, 2)
    assert (totals["human"], totals["indeterminate"]) == (2, 1)
    assert totals["algs"] == [1, 2]
    # The broad toggle moves only the broad lines (FR-028).
    wb, nb = totals["with_broad"], totals["without_broad"]
    assert (
        wb["ai_lines"] - nb["ai_lines"]
        == totals["ai_modified_broad"]
        == nb["human_lines"] - wb["human_lines"]
    )

    # bob is a GitHub member of beta but an override removes him.
    beta = {d["github_login"] for d in owner.get(f"/api/teams/{world.beta}/developers").json()["developers"]}
    assert login["bob"] not in beta and login["carol"] in beta

    # Grafana's v_team_daily agrees with the portal.
    with world.engine.connect() as conn:
        view = conn.execute(
            text(
                "SELECT sum(ai_lines_with_broad) AS ai_wb, sum(ai_lines_without_broad) AS ai_nb, "
                "sum(human_lines_with_broad) AS hu_wb, sum(human_lines_without_broad) AS hu_nb, "
                "sum(indeterminate) AS ind FROM v_team_daily WHERE team = :t"
            ),
            {"t": world.alpha},
        ).one()
    assert (view.ai_wb, view.ai_nb) == (wb["ai_lines"], nb["ai_lines"])
    assert (view.hu_wb, view.hu_nb, view.ind) == (
        wb["human_lines"],
        nb["human_lines"],
        totals["indeterminate"],
    )

    # One developer's own page has the same per-developer figures.
    alice = owner.get(f"/api/developers/{login['alice']}").json()
    assert (alice["ai_unmodified"], alice["ai_modified_broad"], alice["human"], alice["changes"]) == (
        1,
        1,
        1,
        2,
    )
    assert owner.get(f"/developers/{login['alice']}?days=7").status_code == 200
    assert owner.get(f"/api/developers/{login['alice']}?days=0").status_code == 422
    assert owner.get(f"/teams/{world.alpha}/developers").status_code == 200
