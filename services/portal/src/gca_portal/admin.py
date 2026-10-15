"""Administration (T074-T076; FR-016, FR-036): identity overrides, revoking any credential, key rotation.

Admin only (`gca_core.roles.is_admin`). HTML forms post URL-encoded bodies; `/api/...` variants take JSON.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from gca_core.roles import is_admin

from . import admin_keys, credentials
from .backends import CredentialBackend
from .config import PortalConfig
from .keysecret import KeySecret
from .sessions import SessionData

__all__ = ["create_router"]

_OVERRIDES = text("""
    SELECT o.id, o.github_id, a.github_login AS github_login, d.github_login AS developer_login, o.reason,
           o.created_at
    FROM identity_override o
    JOIN developer d ON d.id = o.developer_id
    LEFT JOIN developer a ON a.github_id = o.github_id
    ORDER BY o.created_at DESC
""")


def _forbidden() -> HTTPException:
    return HTTPException(403, detail={"error": "forbidden", "message": "administrators only"})


async def _fields(request: Request) -> dict[str, str]:
    body = await request.body()
    if request.headers.get("content-type", "").startswith("application/json"):
        data = json.loads(body or b"{}")
        return {k: str(v) for k, v in data.items()}
    return {k: v[0] for k, v in parse_qs(body.decode()).items()}


def create_router(
    engine: Engine,
    cfg: PortalConfig,
    backend: CredentialBackend,
    current: Callable[..., SessionData],
    user_client: Callable[[str], Any],
    templates: Jinja2Templates,
    key_secret: KeySecret | None,
) -> APIRouter:
    router = APIRouter()

    async def require_admin(who: SessionData = Depends(current)) -> SessionData:
        if not await is_admin(user_client(who.token), cfg.github_org, who.github_login, cfg.admin_logins):
            raise _forbidden()
        return who

    def _overrides() -> list[Any]:
        with engine.connect() as conn:
            return list(conn.execute(_OVERRIDES).fetchall())

    @router.get("/admin", response_class=HTMLResponse)
    def admin_page(request: Request, who: SessionData = Depends(require_admin)) -> Any:
        with engine.connect() as conn:
            creds = conn.execute(
                text(
                    "SELECT c.id, d.github_login, c.gateway_type::text AS gateway_type, c.issued_at "
                    "FROM gateway_credential c JOIN developer d ON d.id = c.developer_id "
                    "WHERE c.status = 'active' ORDER BY d.github_login"
                )
            ).fetchall()
            keys = conn.execute(
                text(
                    "SELECT id, status::text AS status, retired_at, expires_at FROM key_generation ORDER BY id"
                )
            ).fetchall()
        return templates.TemplateResponse(
            request,
            "admin.html",
            {
                "who": who,
                "overrides": _overrides(),
                "credentials": creds,
                "keys": keys,
                "can_rotate": key_secret is not None,
            },
        )

    # ---------------------------------------------------------------------------------- overrides (T074)
    async def _create_override(request: Request, admin: SessionData) -> uuid.UUID:
        f = await _fields(request)
        login, dev_login, reason = (
            f.get("github_login", "").strip(),
            f.get("developer_login", "").strip(),
            f.get("reason", "").strip(),
        )
        if not (login and dev_login and reason):
            raise HTTPException(
                422,
                detail={
                    "error": "invalid",
                    "message": "github_login, developer_login and reason are required",
                },
            )
        account = await user_client(admin.token).user_by_login(login)
        if account is None:
            raise HTTPException(422, detail={"error": "invalid", "message": f"no GitHub account {login!r}"})
        with engine.begin() as conn:
            dev = conn.execute(
                text("SELECT id FROM developer WHERE lower(github_login) = lower(:l)"), {"l": dev_login}
            ).scalar()
            if dev is None:
                raise HTTPException(
                    422,
                    detail={"error": "invalid", "message": f"{dev_login!r} hasn't signed in to the portal"},
                )
            try:
                return conn.execute(
                    text(
                        "INSERT INTO identity_override (id, github_id, developer_id, reason, created_by, created_at) "
                        "VALUES (gen_random_uuid(), :g, :d, :r, :by, now()) RETURNING id"
                    ),
                    {"g": int(account["id"]), "d": dev, "r": reason, "by": uuid.UUID(admin.developer_id)},
                ).scalar_one()
            except IntegrityError:
                raise HTTPException(
                    409, detail={"error": "conflict", "message": f"{login} already has an override"}
                ) from None

    @router.get("/api/admin/overrides")
    def list_overrides(_: SessionData = Depends(require_admin)) -> JSONResponse:
        return JSONResponse(
            [
                {
                    "id": str(o.id),
                    "github_id": o.github_id,
                    "github_login": o.github_login,
                    "developer_login": o.developer_login,
                    "reason": o.reason,
                    "created_at": o.created_at.isoformat(),
                }
                for o in _overrides()
            ]
        )

    @router.post("/admin/overrides")
    async def add_override(request: Request, admin: SessionData = Depends(require_admin)) -> RedirectResponse:
        await _create_override(request, admin)
        return RedirectResponse("/admin", status_code=303)

    @router.post("/api/admin/overrides")
    async def api_add_override(request: Request, admin: SessionData = Depends(require_admin)) -> JSONResponse:
        return JSONResponse({"id": str(await _create_override(request, admin))}, status_code=201)

    def _delete_override(override_id: uuid.UUID) -> None:
        with engine.begin() as conn:
            if (
                conn.execute(
                    text("DELETE FROM identity_override WHERE id = :i RETURNING id"), {"i": override_id}
                ).first()
                is None
            ):
                raise HTTPException(404, detail={"error": "not_found", "message": "no such override"})

    @router.delete("/admin/overrides/{override_id}")
    def delete_override(override_id: uuid.UUID, _: SessionData = Depends(require_admin)) -> JSONResponse:
        _delete_override(override_id)
        return JSONResponse({"status": "deleted"})

    @router.post("/admin/overrides/{override_id}/delete")
    def delete_override_form(
        override_id: uuid.UUID, _: SessionData = Depends(require_admin)
    ) -> RedirectResponse:
        _delete_override(override_id)
        return RedirectResponse("/admin", status_code=303)

    # ---------------------------------------------------------------------------------- credentials (T075)
    @router.post("/admin/credentials/{credential_id}/revoke")
    def admin_revoke(
        credential_id: uuid.UUID, request: Request, _: SessionData = Depends(require_admin)
    ) -> Any:
        if not credentials.revoke_by_id(engine, backend, cfg.gateway_type, credential_id):
            raise HTTPException(
                404, detail={"error": "not_found", "message": "no active credential with that id"}
            )
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/admin", status_code=303)
        return JSONResponse({"status": "revoked"})

    # ---------------------------------------------------------------------------------- key rotation (T076)
    @router.post("/admin/keys/rotate")
    def rotate(request: Request, _: SessionData = Depends(require_admin)) -> Any:
        if key_secret is None:
            raise HTTPException(
                409, detail={"error": "conflict", "message": "no fingerprint key Secret configured"}
            )
        gen = admin_keys.rotate(engine, key_secret, cfg.retention_days)
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse("/admin", status_code=303)
        return JSONResponse({"active_generation": gen})

    return router
