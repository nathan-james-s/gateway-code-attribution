"""Coverage page (T091; FR-030): links to Grafana's Coverage dashboard, recent capture loss by cause, and the
GitHub accounts credited in PRs that have no gateway credential, so their lines are not observed.

Any signed-in viewer sees the totals. The list of unmapped accounts is for admins only: it spans every
repository, and a viewer may not be able to see all of them. Logins are looked up on GitHub with the admin's own
token; only GitHub account IDs are stored.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .access import Access
from .config import PortalConfig
from .sessions import SessionData

__all__ = ["DAYS", "create_router"]

DAYS = 30
MAX_ACCOUNTS = 200

_LOSS = text("""
    SELECT cause::text AS cause, sum(count) AS lost, count(*) FILTER (WHERE period_end IS NULL) AS ongoing
    FROM capture_loss WHERE period_start > now() - make_interval(days => :d)
    GROUP BY cause ORDER BY sum(count) DESC
""")
_UNMAPPED = text("""
    WITH chosen AS (
        SELECT DISTINCT ON (h.change_id) h.id, h.change_id
        FROM change_head h
        WHERE h.status = 'complete' AND h.completed_at > now() - make_interval(days => :d)
        ORDER BY h.change_id, h.is_final DESC, h.completed_at DESC
    )
    SELECT l.credited_github_id AS github_id, count(*) AS lines, count(DISTINCT x.change_id) AS changes,
           array_agg(DISTINCT r.full_name ORDER BY r.full_name) AS repositories
    FROM chosen x
    JOIN line_result l ON l.change_head_id = x.id
    JOIN change c ON c.id = x.change_id
    JOIN repository r ON r.id = c.repository_id
    WHERE l.outcome = 'not_observed' AND l.credited_github_id IS NOT NULL
    GROUP BY l.credited_github_id
    ORDER BY count(*) DESC
    LIMIT :n
""")


def create_router(
    engine: Engine,
    cfg: PortalConfig,
    access: Access,
    current: Callable[..., SessionData],
    user_client: Callable[[str], Any],
    templates: Jinja2Templates,
) -> APIRouter:
    router = APIRouter()
    logins: dict[int, str | None] = {}  # GitHub account id -> login, looked up once per process

    async def _data(who: SessionData) -> dict[str, Any]:
        is_admin = (await access.roles(who)).admin
        with engine.connect() as conn:
            loss = [dict(r._mapping) for r in conn.execute(_LOSS, {"d": DAYS})]
            unmapped = [dict(r._mapping) for r in conn.execute(_UNMAPPED, {"d": DAYS, "n": MAX_ACCOUNTS})]
        data: dict[str, Any] = {
            "days": DAYS,
            "dashboard_url": f"{cfg.grafana_url.rstrip('/')}/d/gca-coverage",
            "capture_loss": [{**r, "lost": int(r["lost"]), "ongoing": int(r["ongoing"])} for r in loss],
            "unmapped_accounts": len(unmapped),
            "not_observed_lines": sum(int(u["lines"]) for u in unmapped),
        }
        if is_admin:
            user = user_client(who.token)
            for u in unmapped:
                gid = int(u["github_id"])
                if gid not in logins:
                    logins[gid] = await user.login_for_id(gid)
            data["unmapped"] = [
                {
                    "github_id": int(u["github_id"]),
                    "github_login": logins.get(int(u["github_id"])),
                    "lines": int(u["lines"]),
                    "changes": int(u["changes"]),
                    "repositories": list(u["repositories"]),
                }
                for u in unmapped
            ]
        return data

    @router.get("/coverage", response_class=HTMLResponse)
    async def coverage_page(request: Request, who: SessionData = Depends(current)) -> Any:
        return templates.TemplateResponse(request, "coverage.html", {"who": who, "c": await _data(who)})

    @router.get("/api/coverage")
    async def api_coverage(who: SessionData = Depends(current)) -> JSONResponse:
        return JSONResponse(await _data(who))

    return router
