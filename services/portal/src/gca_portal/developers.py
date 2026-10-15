"""Per-developer views (T085; FR-026, FR-028, FR-029; contracts/portal-http.md).

- `GET /developers/{github_login}`: one developer's totals over a period.
- `GET /teams/{slug}/developers`: a per-developer breakdown inside a team. A line counts for the team when its
  developer was a member on the merge date, as in Grafana's `v_team_daily`, so the rows add up to the team total.

Figures come from `LineResult.credited_developer_id` on the final heads of changes merged in the period, with and
without broad matches, and name the algorithm versions behind them. Both routes check `can_view_developer` or
`can_view_team` and answer 403 without saying whether the developer or team exists. No code is ever shown.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core.roles import EFFECTIVE_MEMBERS_AT, can_view_developer, can_view_team

from .access import Access, error
from .sessions import SessionData

__all__ = ["PERIODS", "create_router", "figures"]

PERIODS = (7, 30, 90, 365)
DEFAULT_DAYS = 30

_COUNTS = """
    count(DISTINCT c.id) AS changes,
    coalesce(array_agg(DISTINCT h.alg ORDER BY h.alg), '{}') AS algs,
    count(*) FILTER (WHERE l.outcome = 'ai_unmodified') AS ai_unmodified,
    count(*) FILTER (WHERE l.outcome = 'ai_modified' AND l.tier = 'anchored') AS ai_modified_anchored,
    count(*) FILTER (WHERE l.outcome = 'ai_modified' AND l.tier = 'broad') AS ai_modified_broad,
    count(*) FILTER (WHERE l.outcome = 'human') AS human,
    count(*) FILTER (WHERE l.outcome = 'indeterminate') AS indeterminate
"""
_FINAL_LINES = """
    FROM change c
    JOIN change_head h ON h.id = c.final_head_id
    JOIN line_result l ON l.change_head_id = h.id
    WHERE c.state = 'merged' AND c.merged_at >= :since
"""
_DEVELOPER = text(f"SELECT {_COUNTS} {_FINAL_LINES} AND l.credited_developer_id = :d")
# Membership as of the merge date: the same rule as v_team_daily (migration 0004). The ROLLUP row (login NULL) is
# the team total, so it is exactly the sum of the developer rows (except `changes`: a PR can have several authors).
_TEAM = text(f"""
    SELECT d.github_login, {_COUNTS}
    FROM change c
    JOIN change_head h ON h.id = c.final_head_id
    JOIN line_result l ON l.change_head_id = h.id
    JOIN developer d ON d.id = l.credited_developer_id
    WHERE c.state = 'merged' AND c.merged_at >= :since
      AND (SELECT bool_or(m.source = 'github' OR m.override_action = 'add')
                  AND NOT bool_or(m.source = 'override' AND m.override_action = 'remove')
             FROM team_membership m
            WHERE m.team_id = :team AND m.developer_id = l.credited_developer_id
              AND m.valid_from <= c.merged_at AND (m.valid_to IS NULL OR c.merged_at < m.valid_to)) IS TRUE
    GROUP BY ROLLUP (d.github_login)
""")  # noqa: S608
_MEMBERS = text(f"""
    SELECT d.github_login FROM ({EFFECTIVE_MEMBERS_AT}) e JOIN developer d ON d.id = e.developer_id
    WHERE e.team_id = :team
""")  # noqa: S608


def figures(row: Any) -> dict[str, Any]:
    """Counts with and without broad matches (FR-028). Without them, broad lines count as human."""
    unmod, anch, broad, human = (
        int(row.ai_unmodified),
        int(row.ai_modified_anchored),
        int(row.ai_modified_broad),
        int(row.human),
    )
    attributable = unmod + anch + broad + human

    def pct(n: int) -> float | None:
        return round(100.0 * n / attributable, 1) if attributable else None

    return {
        "changes": int(row.changes),
        "algs": list(row.algs or []),
        "ai_unmodified": unmod,
        "ai_modified_anchored": anch,
        "ai_modified_broad": broad,
        "human": human,
        "indeterminate": int(row.indeterminate),
        "attributable_lines": attributable,
        "with_broad": {
            "ai_lines": unmod + anch + broad,
            "human_lines": human,
            "ai_pct": pct(unmod + anch + broad),
        },
        "without_broad": {
            "ai_lines": unmod + anch,
            "human_lines": human + broad,
            "ai_pct": pct(unmod + anch),
        },
    }


def _days(days: int | None) -> int:
    if days is None:
        return DEFAULT_DAYS
    if not 1 <= days <= 3650:
        raise error(422, "invalid", "days must be between 1 and 3650")
    return days


def _forbidden() -> Exception:
    return error(403, "forbidden", "you can't view this")


def create_router(
    engine: Engine, access: Access, current: Callable[..., SessionData], templates: Jinja2Templates
) -> APIRouter:
    router = APIRouter()

    async def _developer(who: SessionData, login: str, days: int) -> dict[str, Any]:
        roles = await access.roles(who)
        with engine.connect() as conn:
            dev = conn.execute(
                text("SELECT id, github_login FROM developer WHERE lower(github_login) = lower(:l)"),
                {"l": login},
            ).first()
            if dev is None or not can_view_developer(conn, roles, dev.id):
                raise _forbidden()
            since = conn.execute(text("SELECT now()")).scalar_one() - timedelta(days=days)
            row = conn.execute(_DEVELOPER, {"since": since, "d": dev.id}).one()
        return {"github_login": dev.github_login, "days": days, **figures(row)}

    async def _team(who: SessionData, slug: str, days: int) -> dict[str, Any]:
        roles = await access.roles(who)
        with engine.connect() as conn:
            team = conn.execute(
                text("SELECT id, slug, name FROM team WHERE lower(slug) = lower(:s)"), {"s": slug}
            ).first()
            if team is None or not can_view_team(conn, roles, uuid.UUID(str(team.id))):
                raise _forbidden()
            now = conn.execute(text("SELECT now()")).scalar_one()
            rows, totals = {}, figures(_ZERO)
            for r in conn.execute(_TEAM, {"since": now - timedelta(days=days), "team": team.id}):
                if r.github_login is None:
                    totals = figures(r)
                else:
                    rows[r.github_login] = figures(r)
            members = {r.github_login for r in conn.execute(_MEMBERS, {"t": now, "team": team.id})}
        empty = figures(_ZERO)
        developers = [
            {"github_login": login, "current_member": login in members, **rows.get(login, empty)}
            for login in sorted(set(rows) | members, key=str.lower)
        ]
        return {
            "team": team.slug,
            "name": team.name,
            "days": days,
            "developers": developers,
            "totals": totals,
        }

    @router.get("/developers/{github_login}", response_class=HTMLResponse)
    async def developer_page(
        github_login: str, request: Request, days: int | None = None, who: SessionData = Depends(current)
    ) -> Any:
        data = await _developer(who, github_login, _days(days))
        return templates.TemplateResponse(
            request, "developer.html", {"who": who, "d": data, "periods": PERIODS}
        )

    @router.get("/api/developers/{github_login}")
    async def api_developer(
        github_login: str, days: int | None = None, who: SessionData = Depends(current)
    ) -> JSONResponse:
        return JSONResponse(await _developer(who, github_login, _days(days)))

    @router.get("/teams/{slug}/developers", response_class=HTMLResponse)
    async def team_page(
        slug: str, request: Request, days: int | None = None, who: SessionData = Depends(current)
    ) -> Any:
        data = await _team(who, slug, _days(days))
        return templates.TemplateResponse(
            request, "team_developers.html", {"who": who, "t": data, "periods": PERIODS}
        )

    @router.get("/api/teams/{slug}/developers")
    async def api_team(
        slug: str, days: int | None = None, who: SessionData = Depends(current)
    ) -> JSONResponse:
        return JSONResponse(await _team(who, slug, _days(days)))

    return router


class _Zero:
    changes = ai_unmodified = ai_modified_anchored = ai_modified_broad = human = indeterminate = 0
    algs: tuple[int, ...] = ()


_ZERO = _Zero()
