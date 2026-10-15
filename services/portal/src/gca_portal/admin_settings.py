"""Settings administration (T084; FR-021, FR-029): per-developer views, who sees them, matching window, retention
and exclusion rules. Admin only.

The services read these from `portal_settings` as they work, so a change applies to the next PR check and the
next daily maintenance run. A changed Helm value overrides what is set here at the next upgrade
(gca_core.bootstrap.apply_settings).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core.roles import VISIBLE_ROLE_NAMES

from .access import error, form_lists
from .sessions import SessionData

__all__ = ["create_router"]

MAX_RULES = 200
MAX_RULE_LENGTH = 512
TRUE = {"true", "on", "1", "yes"}

_SELECT = text(
    "SELECT per_developer_enabled, visible_roles, matching_window_days, retention_days, exclusion_rules "
    "FROM portal_settings WHERE id = 1"
)


def _as_dict(row: Any) -> dict[str, Any]:
    return {
        "per_developer_enabled": bool(row.per_developer_enabled),
        "visible_roles": list(row.visible_roles),
        "matching_window_days": int(row.matching_window_days),
        "retention_days": int(row.retention_days),
        "exclusion_rules": list(row.exclusion_rules),
    }


def _positive_int(f: dict[str, list[str]], name: str, current: int) -> int:
    raw = (f.get(name) or [str(current)])[0].strip()
    try:
        value = int(raw)
    except ValueError:
        raise error(422, "invalid", f"{name} must be a whole number of days") from None
    if not 1 <= value <= 3650:
        raise error(422, "invalid", f"{name} must be between 1 and 3650 days")
    return value


def parse(f: dict[str, list[str]], current: dict[str, Any]) -> dict[str, Any]:
    """Validate a submitted settings form. Fields left out keep their current value (a JSON body can be partial);
    an HTML form always sends `form=1`, so an unticked checkbox there means "off"."""
    html = "form" in f
    out = dict(current)
    if "per_developer_enabled" in f or html:
        out["per_developer_enabled"] = (f.get("per_developer_enabled") or ["false"])[-1].lower() in TRUE
    if "visible_roles" in f or html:
        roles = [r.strip() for v in f.get("visible_roles", []) for r in v.split(",") if r.strip()]
        unknown = sorted(set(roles) - set(VISIBLE_ROLE_NAMES))
        if unknown:
            raise error(422, "invalid", f"unknown roles {unknown}; use {list(VISIBLE_ROLE_NAMES)}")
        out["visible_roles"] = [r for r in VISIBLE_ROLE_NAMES if r in roles]
    out["matching_window_days"] = _positive_int(f, "matching_window_days", current["matching_window_days"])
    out["retention_days"] = _positive_int(f, "retention_days", current["retention_days"])
    if out["retention_days"] < out["matching_window_days"]:
        raise error(
            422,
            "invalid",
            "retention_days can't be shorter than matching_window_days: captures would be gone "
            "before the window closes",
        )
    if "exclusion_rules" in f:
        rules = [r.strip() for v in f["exclusion_rules"] for r in v.splitlines() if r.strip()]
        if len(rules) > MAX_RULES or any(len(r) > MAX_RULE_LENGTH for r in rules):
            raise error(422, "invalid", f"at most {MAX_RULES} rules of up to {MAX_RULE_LENGTH} characters")
        out["exclusion_rules"] = rules
    return out


def create_router(engine: Engine, require_admin: Callable[..., Any], templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _current() -> dict[str, Any]:
        with engine.connect() as conn:
            return _as_dict(conn.execute(_SELECT).one())

    @router.get("/admin/settings", response_class=HTMLResponse)
    def settings_page(request: Request, who: SessionData = Depends(require_admin)) -> Any:
        return templates.TemplateResponse(
            request,
            "admin_settings.html",
            {"who": who, "s": _current(), "role_names": VISIBLE_ROLE_NAMES},
        )

    @router.get("/api/admin/settings")
    def api_settings(_: SessionData = Depends(require_admin)) -> JSONResponse:
        return JSONResponse(_current())

    async def _save(request: Request) -> dict[str, Any]:
        new = parse(await form_lists(request), _current())
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE portal_settings SET per_developer_enabled = :per_developer_enabled, "
                    "visible_roles = :visible_roles, matching_window_days = :matching_window_days, "
                    "retention_days = :retention_days, exclusion_rules = :exclusion_rules WHERE id = 1"
                ),
                new,
            )
        return new

    @router.post("/admin/settings")
    async def save(request: Request, _: SessionData = Depends(require_admin)) -> RedirectResponse:
        await _save(request)
        return RedirectResponse("/admin/settings", status_code=303)

    @router.post("/api/admin/settings")
    async def api_save(request: Request, _: SessionData = Depends(require_admin)) -> JSONResponse:
        return JSONResponse(await _save(request))

    return router
