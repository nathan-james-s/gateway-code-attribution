"""Team administration (T084; FR-027): extra in-stack teams, and membership overrides on any team.

Overrides are `TeamMembership` rows with `source=override`. Like sync, they are never deleted: changing or clearing
one closes the open row (`valid_to=now()`), so team totals keep "membership as of the merge date". Team sync never
touches override rows. Admin only.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from gca_core.roles import EFFECTIVE_MEMBERS_AT

from .access import error, form_fields
from .admin_roles import developer_id, team_id
from .sessions import SessionData

__all__ = ["create_router"]

SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
ACTIONS = ("create", "add_member", "remove_member", "clear_member")

_TEAMS = text(f"""
    SELECT t.id, t.slug, t.name, t.source::text AS source, t.synced_at,
           coalesce(array_agg(d.github_login ORDER BY d.github_login) FILTER (WHERE d.id IS NOT NULL), '{{}}')
               AS members,
           (SELECT coalesce(array_agg(ld.github_login ORDER BY ld.github_login), '{{}}')
              FROM team_lead l JOIN developer ld ON ld.id = l.developer_id
             WHERE l.team_id = t.id AND l.source = 'github_maintainer') AS maintainers,
           (SELECT coalesce(array_agg(od.github_login || ':' || o.override_action::text
                                      ORDER BY od.github_login), '{{}}')
              FROM team_membership o JOIN developer od ON od.id = o.developer_id
             WHERE o.team_id = t.id AND o.source = 'override' AND o.valid_to IS NULL) AS overrides
    FROM team t
    LEFT JOIN ({EFFECTIVE_MEMBERS_AT}) e ON e.team_id = t.id
    LEFT JOIN developer d ON d.id = e.developer_id
    GROUP BY t.id
    ORDER BY t.slug
""")  # noqa: S608 - EFFECTIVE_MEMBERS_AT is a constant


def create_router(engine: Engine, require_admin: Callable[..., Any], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _teams() -> list[Any]:
        with engine.connect() as conn:
            now = conn.execute(text("SELECT now()")).scalar_one()
            return list(conn.execute(_TEAMS, {"t": now}).fetchall())

    @router.get("/admin/teams", response_class=HTMLResponse)
    def teams_page(request: Request, who: SessionData = Depends(require_admin)) -> Any:
        return templates.TemplateResponse(request, "admin_teams.html", {"who": who, "teams": _teams()})

    @router.get("/api/admin/teams")
    def api_teams(_: SessionData = Depends(require_admin)) -> JSONResponse:
        return JSONResponse(
            [
                {
                    "slug": t.slug,
                    "name": t.name,
                    "source": t.source,
                    "synced_at": t.synced_at.isoformat() if t.synced_at else None,
                    "members": list(t.members),
                    "github_maintainers": list(t.maintainers),
                    "overrides": [
                        {"github_login": o.rsplit(":", 1)[0], "action": o.rsplit(":", 1)[1]}
                        for o in t.overrides
                    ],
                }
                for t in _teams()
            ]
        )

    async def _change(request: Request) -> str:
        f = await form_fields(request)
        action, slug = f.get("action", "").strip(), f.get("team", "").strip().lower()
        if action not in ACTIONS or not slug:
            raise error(422, "invalid", f"team and action ({'|'.join(ACTIONS)}) are required")
        with engine.begin() as conn:
            if action == "create":
                name = f.get("name", "").strip() or slug
                if not SLUG.match(slug):
                    raise error(422, "invalid", "a team slug is lowercase letters, digits, '-' and '_'")
                try:
                    with conn.begin_nested():
                        conn.execute(
                            text(
                                "INSERT INTO team (id, slug, name, source) "
                                "VALUES (gen_random_uuid(), :s, :n, 'manual')"
                            ),
                            {"s": slug, "n": name},
                        )
                except IntegrityError:
                    raise error(409, "conflict", f"a team {slug!r} already exists") from None
                return "created"
            team = team_id(conn, slug)
            dev = developer_id(conn, f.get("github_login", "").strip())
            conn.execute(
                text(
                    "UPDATE team_membership SET valid_to = greatest(now(), valid_from + interval '1 microsecond') "
                    "WHERE team_id = :t AND developer_id = :d AND source = 'override' AND valid_to IS NULL"
                ),
                {"t": team, "d": dev},
            )
            if action != "clear_member":
                conn.execute(
                    text(
                        "INSERT INTO team_membership (id, team_id, developer_id, source, override_action, valid_from) "
                        "VALUES (:id, :t, :d, 'override', CAST(:a AS override_action), now())"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "t": team,
                        "d": dev,
                        "a": "add" if action == "add_member" else "remove",
                    },
                )
        return action

    @router.post("/admin/teams")
    async def change_team(request: Request, _: SessionData = Depends(require_admin)) -> RedirectResponse:
        await _change(request)
        return RedirectResponse("/admin/teams", status_code=303)

    @router.post("/api/admin/teams")
    async def api_change_team(request: Request, _: SessionData = Depends(require_admin)) -> JSONResponse:
        return JSONResponse({"status": await _change(request)})

    return router
