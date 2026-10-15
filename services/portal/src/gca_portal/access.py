"""Viewer roles for portal requests (T083; FR-029, FR-029a; contracts/portal-http.md "Roles").

GitHub-derived roles are checked live with the viewer's own token and cached per login for at most 60 seconds;
in-stack grants and revokes are read on every request. Errors are flat JSON, and a failed role check never
reveals whether the developer or team asked for exists.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

from fastapi import Depends, HTTPException, Request
from sqlalchemy.engine import Engine

from gca_core.roles import GithubRoleCache, Roles, github_roles, roles_for

from .config import PortalConfig
from .sessions import SessionData

__all__ = ["Access", "error", "form_fields", "form_lists", "wants_html"]


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"error": code, "message": message})


def wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "") and not request.url.path.startswith("/api/")


async def form_lists(request: Request) -> dict[str, list[str]]:
    """A URL-encoded form or a JSON object, as lists of strings (checkbox groups repeat a name)."""
    body = await request.body()
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            raise error(422, "invalid", "the body isn't valid JSON") from None
        if not isinstance(data, dict):
            raise error(422, "invalid", "the body must be a JSON object")
        return {k: [str(x) for x in v] if isinstance(v, list) else [_text(v)] for k, v in data.items()}
    return {k: v for k, v in parse_qs(body.decode(), keep_blank_values=True).items()}


def _text(v: Any) -> str:
    return ("true" if v else "false") if isinstance(v, bool) else str(v)


async def form_fields(request: Request) -> dict[str, str]:
    return {k: (v[0] if v else "") for k, v in (await form_lists(request)).items()}


class Access:
    def __init__(
        self,
        engine: Engine,
        cfg: PortalConfig,
        user_client: Callable[[str], Any],
        cache: GithubRoleCache | None = None,
    ) -> None:
        self.engine, self.cfg, self.user_client = engine, cfg, user_client
        self.cache = cache or GithubRoleCache()

    async def roles(self, who: SessionData) -> Roles:
        github = await self.cache.get(
            who.github_login,
            lambda: github_roles(self.user_client(who.token), self.cfg.github_org, who.github_login),
        )
        with self.engine.connect() as conn:
            return roles_for(
                conn, uuid.UUID(who.developer_id), who.github_login, github, self.cfg.admin_logins
            )

    def admin_dependency(self, current: Callable[..., SessionData]) -> Callable[..., Any]:
        async def require_admin(who: SessionData = Depends(current)) -> SessionData:
            if not (await self.roles(who)).admin:
                raise error(403, "forbidden", "administrators only")
            return who

        return require_admin
