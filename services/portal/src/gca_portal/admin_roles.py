"""Role administration (T084; FR-029, FR-029a): grant or revoke the admin and team-lead roles in the stack.

A grant or revoke overrides the GitHub-derived default for one (developer, role, team) and applies at the
developer's next page load. `action=clear` removes the override, so the GitHub default applies again. Admin only.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from .access import error, form_fields
from .sessions import SessionData

__all__ = ["create_router", "developer_id"]

_GRANTS = text("""
    SELECT g.id, d.github_login, g.role::text AS role, t.slug AS team, g.action::text AS action,
           b.github_login AS created_by, g.created_at
    FROM viewer_role_grant g
    JOIN developer d ON d.id = g.developer_id
    JOIN developer b ON b.id = g.created_by
    LEFT JOIN team t ON t.id = g.team_id
    ORDER BY d.github_login, g.role, t.slug
""")
_MAINTAINERS = text("""
    SELECT t.slug AS team, d.github_login
    FROM team_lead l JOIN team t ON t.id = l.team_id JOIN developer d ON d.id = l.developer_id
    WHERE l.source = 'github_maintainer'
    ORDER BY t.slug, d.github_login
""")


def developer_id(conn: Connection, login: str) -> uuid.UUID:
    dev = conn.execute(
        text("SELECT id FROM developer WHERE lower(github_login) = lower(:l)"), {"l": login}
    ).scalar()
    if dev is None:
        raise error(422, "invalid", f"{login!r} hasn't signed in to the portal")
    return uuid.UUID(str(dev))


def team_id(conn: Connection, slug: str) -> uuid.UUID:
    team = conn.execute(text("SELECT id FROM team WHERE lower(slug) = lower(:s)"), {"s": slug}).scalar()
    if team is None:
        raise error(422, "invalid", f"no team {slug!r}")
    return uuid.UUID(str(team))


def create_router(engine: Engine, require_admin: Callable[..., Any], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _rows() -> dict[str, list[Any]]:
        with engine.connect() as conn:
            return {
                "grants": list(conn.execute(_GRANTS).fetchall()),
                "maintainers": list(conn.execute(_MAINTAINERS).fetchall()),
            }

    @router.get("/admin/roles", response_class=HTMLResponse)
    def roles_page(request: Request, who: SessionData = Depends(require_admin)) -> Any:
        return templates.TemplateResponse(request, "admin_roles.html", {"who": who, **_rows()})

    @router.get("/api/admin/roles")
    def api_roles(_: SessionData = Depends(require_admin)) -> JSONResponse:
        rows = _rows()
        return JSONResponse(
            {
                "grants": [
                    {
                        "id": str(g.id),
                        "github_login": g.github_login,
                        "role": g.role,
                        "team": g.team,
                        "action": g.action,
                        "created_by": g.created_by,
                        "created_at": g.created_at.isoformat(),
                    }
                    for g in rows["grants"]
                ],
                "github_maintainers": [
                    {"team": m.team, "github_login": m.github_login} for m in rows["maintainers"]
                ],
            }
        )

    async def _set(request: Request, admin: SessionData) -> str:
        f = await form_fields(request)
        login, role, slug, action = (
            f.get("github_login", "").strip(),
            f.get("role", "").strip(),
            f.get("team", "").strip(),
            f.get("action", "").strip(),
        )
        if role not in ("admin", "team_lead") or action not in ("grant", "revoke", "clear") or not login:
            raise error(
                422,
                "invalid",
                "github_login, role (admin|team_lead) and action (grant|revoke|clear) are required",
            )
        if role == "team_lead" and not slug:
            raise error(422, "invalid", "a team-lead role needs a team")
        if role == "admin" and action == "revoke" and login.lower() == admin.github_login.lower():
            raise error(409, "conflict", "you can't revoke your own admin role")
        with engine.begin() as conn:
            dev = developer_id(conn, login)
            team = team_id(conn, slug) if role == "team_lead" else None
            # One override per (developer, role, team): the latest decision replaces any earlier one.
            conn.execute(
                text(
                    "DELETE FROM viewer_role_grant WHERE developer_id = :d AND role = CAST(:r AS viewer_role) "
                    "AND team_id IS NOT DISTINCT FROM CAST(:t AS uuid)"
                ),
                {"d": dev, "r": role, "t": team},
            )
            if action != "clear":
                conn.execute(
                    text(
                        "INSERT INTO viewer_role_grant (id, developer_id, role, team_id, action, created_by, created_at) "
                        "VALUES (gen_random_uuid(), :d, CAST(:r AS viewer_role), CAST(:t AS uuid), CAST(:a AS grant_action), :by, now())"
                    ),
                    {"d": dev, "r": role, "t": team, "a": action, "by": uuid.UUID(admin.developer_id)},
                )
        return action

    @router.post("/admin/roles")
    async def set_role(request: Request, admin: SessionData = Depends(require_admin)) -> RedirectResponse:
        await _set(request, admin)
        return RedirectResponse("/admin/roles", status_code=303)

    @router.post("/api/admin/roles")
    async def api_set_role(request: Request, admin: SessionData = Depends(require_admin)) -> JSONResponse:
        return JSONResponse({"status": await _set(request, admin)})

    return router
