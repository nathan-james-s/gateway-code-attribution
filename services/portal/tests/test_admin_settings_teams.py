"""Settings and team administration (T084): validation, partial JSON updates, and membership overrides."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_portal.admin_settings import parse
from gca_portal.app import create_app
from gca_portal.config import PortalConfig

from .test_admin import FakeBackend, FakeUser

CURRENT = {
    "per_developer_enabled": True,
    "visible_roles": ["admin", "team_lead"],
    "matching_window_days": 14,
    "retention_days": 90,
    "exclusion_rules": ["**/*.lock"],
}


def _admin(engine: Engine) -> TestClient:
    login = f"admin-{uuid.uuid4().hex[:6]}"
    user = FakeUser(9_000_000 + uuid.uuid4().int % 1_000_000, login)

    async def exchange(*args: Any) -> FakeUser:
        return user

    cfg = PortalConfig(github_client_id="cid", admin_logins=[login])
    c = TestClient(create_app(engine, cfg, FakeBackend(), exchange=exchange, user_client=lambda tok: user))
    r = c.get("/auth/login", follow_redirects=False)
    state = re.search(r"state=([^&]+)", r.headers["location"]).group(1)  # type: ignore[union-attr]
    c.get(f"/auth/callback?code=x&state={state}", follow_redirects=False)
    return c


@pytest.fixture
def restore_settings(pg_engine: Engine) -> Iterator[None]:
    with pg_engine.connect() as conn:
        saved = (
            conn.execute(
                text(
                    "SELECT per_developer_enabled, visible_roles, matching_window_days, retention_days, exclusion_rules "
                    "FROM portal_settings WHERE id = 1"
                )
            )
            .mappings()
            .one()
        )
    yield
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE portal_settings SET per_developer_enabled = :per_developer_enabled, "
                "visible_roles = :visible_roles, matching_window_days = :matching_window_days, "
                "retention_days = :retention_days, exclusion_rules = :exclusion_rules WHERE id = 1"
            ),
            dict(saved),
        )


def test_parse_html_form_unticked_checkbox_means_off() -> None:
    out = parse(
        {"form": ["1"], "visible_roles": ["admin"], "exclusion_rules": ["a/**\n\n b/*.js \n"]}, CURRENT
    )
    assert out["per_developer_enabled"] is False
    assert out["visible_roles"] == ["admin"] and out["exclusion_rules"] == ["a/**", "b/*.js"]


def test_parse_partial_json_keeps_the_rest() -> None:
    assert parse({"retention_days": ["120"]}, CURRENT) == {**CURRENT, "retention_days": 120}


@pytest.mark.parametrize(
    "body",
    [
        {"matching_window_days": ["0"]},
        {"matching_window_days": ["two"]},
        {"retention_days": ["7"]},  # shorter than the 14-day window
        {"visible_roles": ["everyone"]},
        {"exclusion_rules": ["x" * 600]},
    ],
)
def test_parse_rejects(body: dict[str, list[str]]) -> None:
    with pytest.raises(Exception) as exc:
        parse(body, CURRENT)
    assert getattr(exc.value, "status_code", None) == 422


def test_settings_round_trip(pg_engine: Engine, restore_settings: None) -> None:
    c = _admin(pg_engine)
    r = c.post("/api/admin/settings", json={"matching_window_days": 21, "exclusion_rules": ["**/gen/**"]})
    assert r.status_code == 200
    got = c.get("/api/admin/settings").json()
    assert got["matching_window_days"] == 21 and got["exclusion_rules"] == ["**/gen/**"]
    # The HTML form posts URL-encoded fields, repeating visible_roles for each ticked box.
    form = "form=1&per_developer_enabled=on&visible_roles=admin&visible_roles=other&matching_window_days=14&retention_days=90&exclusion_rules=**%2F*.lock"
    r = c.post(
        "/admin/settings",
        content=form,
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    got = c.get("/api/admin/settings").json()
    assert got["visible_roles"] == ["admin", "other"] and got["exclusion_rules"] == ["**/*.lock"]
    assert "Per-developer views" in c.get("/admin/settings").text
    # The PR check reads these as it works (exclusions.load_rules, the matching window).
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT exclusion_rules FROM portal_settings")).scalar() == ["**/*.lock"]


def test_team_overrides(pg_engine: Engine) -> None:
    c = _admin(pg_engine)
    slug = f"platform-{uuid.uuid4().hex[:6]}"
    member = f"m-{uuid.uuid4().hex[:6]}"
    with pg_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO developer (id, github_id, github_login) VALUES (gen_random_uuid(), :g, :l)"),
            {"g": 9_500_000 + uuid.uuid4().int % 100_000, "l": member},
        )

    def team() -> dict[str, Any]:
        return next(t for t in c.get("/api/admin/teams").json() if t["slug"] == slug)

    assert c.post("/api/admin/teams", json={"action": "create", "team": slug, "name": "Platform"}).json() == {
        "status": "created"
    }
    assert c.post("/api/admin/teams", json={"action": "create", "team": slug}).status_code == 409
    assert c.post("/api/admin/teams", json={"action": "create", "team": "Bad Slug!"}).status_code == 422
    assert team()["source"] == "manual" and team()["members"] == []

    c.post("/api/admin/teams", json={"action": "add_member", "team": slug, "github_login": member})
    assert team()["members"] == [member] and team()["overrides"] == [
        {"github_login": member, "action": "add"}
    ]
    c.post("/api/admin/teams", json={"action": "remove_member", "team": slug, "github_login": member})
    assert team()["members"] == [] and team()["overrides"] == [{"github_login": member, "action": "remove"}]
    c.post("/api/admin/teams", json={"action": "clear_member", "team": slug, "github_login": member})
    assert team()["overrides"] == []
    with pg_engine.connect() as conn:  # history kept: the add and remove rows, both closed
        rows = conn.execute(
            text(
                "SELECT count(*), count(valid_to) FROM team_membership m JOIN team t ON t.id = m.team_id "
                "WHERE t.slug = :s"
            ),
            {"s": slug},
        ).one()
    assert tuple(rows) == (2, 2)
    unknown = c.post(
        "/api/admin/teams", json={"action": "add_member", "team": slug, "github_login": "nobody-xyz"}
    )
    assert unknown.status_code == 422
    assert slug in c.get("/admin/teams").text and "Viewer roles" in c.get("/admin/roles").text
