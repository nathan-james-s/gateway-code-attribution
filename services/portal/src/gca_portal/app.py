"""Portal: GitHub sign-in, personal gateway credentials, setup help, per-line PR results (T048-T051), and
role-checked per-developer views with role, team and settings administration (T083-T085).

Responses never contain code or prompt text (contracts/portal-http.md). Per-line views show positions and
outcomes, linking to GitHub for the line itself.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gca_core import github as gh
from gca_core.db.models_identity import Developer, GatewayCredential

from . import admin, admin_keys, admin_roles, admin_settings, admin_teams, coverage, credentials, developers
from .access import Access
from .backends import CredentialBackend, make_backend
from .config import PortalConfig, portal_config
from .keysecret import KeySecret
from .sessions import SessionData, SessionStore

log = logging.getLogger("gca.portal")
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
COOKIE = "gca_session"
RESYNC_SECONDS = 30

# Per-tool routing (research R6). {url} is the gateway's public URL.
TOOLS = [
    {
        "tool": "Claude Code",
        "set": "ANTHROPIC_BASE_URL={url}  ANTHROPIC_AUTH_TOKEN=<your key>",
        "model": "demo-anthropic (or a configured model)",
    },
    {
        "tool": "Codex CLI",
        "set": '~/.codex/config.toml: [model_providers.gca] base_url="{url}/v1" '
        'env_key="GCA_KEY" wire_api="responses"  (run `codex logout` first)',
        "model": "demo-openai",
    },
    {
        "tool": "Gemini CLI",
        "set": "GOOGLE_GEMINI_BASE_URL={url}  GEMINI_API_KEY=<your key>",
        "model": "demo-gemini",
    },
    {
        "tool": "OpenCode",
        "set": 'opencode.json provider: baseURL "{url}/v1", apiKey "<your key>"',
        "model": "demo-openai",
    },
]

# Latest completed head for a PR (the final head at merge wins). Positions and outcomes only, never content.
LATEST_HEAD_SQL = text("""
    SELECT h.id, h.head_sha, h.coverage_status, h.counts, h.alg, h.excluded_paths, h.is_final
    FROM change_head h
    JOIN change c ON c.id = h.change_id
    JOIN repository r ON r.id = c.repository_id
    WHERE r.full_name = :fn AND c.pr_number = :pr AND h.status = 'complete'
    ORDER BY h.is_final DESC, h.completed_at DESC
    LIMIT 1
""")
LINES_SQL = text("""
    SELECT l.file_path, l.line_no, l.outcome::text AS outcome, l.tier::text AS tier,
           l.confidence::text AS confidence, l.similarity, d.github_login
    FROM line_result l
    LEFT JOIN developer d ON d.id = l.credited_developer_id
    WHERE l.change_head_id = :h
    ORDER BY l.file_path, l.line_no
""")


def create_app(
    engine: Engine,
    cfg: PortalConfig | None = None,
    backend: CredentialBackend | None = None,
    exchange: Callable[..., Any] = gh.exchange_code,
    user_client: Callable[[str], Any] = gh.UserClient.from_token,
    key_secret: KeySecret | None = None,
) -> FastAPI:
    cfg = cfg or portal_config()
    if key_secret is None and cfg.fingerprint_secret:
        key_secret = KeySecret(cfg.namespace, cfg.fingerprint_secret)
    store = SessionStore(cfg.session_ttl_seconds)
    access = Access(engine, cfg, user_client)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(key_sync_loop())
        yield
        task.cancel()

    async def key_sync_loop() -> None:
        """Keep the gateway's key list in line with the database. Runs at start-up and every RESYNC_SECONDS,
        which also re-renders the live config after `helm upgrade` changes the base config."""
        while True:
            try:
                await asyncio.to_thread(backend.ensure)  # the gateway can start before migrations run
                await asyncio.to_thread(sync_keys)
                if key_secret is not None:  # expired key generations leave the Secret (T076)
                    await asyncio.to_thread(admin_keys.sync_secret, engine, key_secret)
            except Exception as exc:
                log.warning("key sync failed, retrying: %s", type(exc).__name__)
            await asyncio.sleep(RESYNC_SECONDS)

    app = FastAPI(title="Gateway Code Attribution portal", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.engine = engine
    app.state.cfg = cfg
    app.state.store = store
    if backend is None:
        backend = make_backend(cfg)
    app.state.backend = backend
    app.state.access = access
    pending_states: dict[str, float] = {}

    @app.exception_handler(HTTPException)
    async def _errors(request: Request, exc: HTTPException) -> Response:
        # Contract errors are flat JSON: {"error": <code>, "message": <text>}.
        if exc.status_code == 303 and exc.headers:
            return RedirectResponse(exc.headers["Location"], status_code=303)
        body = (
            exc.detail if isinstance(exc.detail, dict) else {"error": "invalid", "message": str(exc.detail)}
        )
        return JSONResponse(body, status_code=exc.status_code)

    def db() -> Session:
        return Session(engine, expire_on_commit=False)

    def current(request: Request) -> SessionData:
        data = store.get(request.cookies.get(COOKIE))
        if data is None:
            if request.url.path.startswith("/api/"):
                raise HTTPException(401, detail={"error": "unauthenticated", "message": "sign in first"})
            raise HTTPException(303, headers={"Location": "/auth/login"})
        return data

    def sync_keys() -> None:
        credentials.sync(engine, backend)

    # ------------------------------------------------------------------ health
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    # ------------------------------------------------------------------ auth (FR-016)
    @app.get("/auth/login")
    def login() -> RedirectResponse:
        url, state = gh.authorize_url(cfg.github_client_id, f"{cfg.public_url}/auth/callback")
        pending_states[state] = datetime.now(UTC).timestamp()
        return RedirectResponse(url, status_code=302)

    @app.get("/auth/callback")
    async def callback(request: Request, code: str, state: str) -> Response:
        if pending_states.pop(state, None) is None:
            # Browsers sometimes repeat this request; the first one already finished signing in.
            if store.get(request.cookies.get(COOKIE)):
                return RedirectResponse("/me", status_code=303)
            raise HTTPException(400, detail={"error": "invalid", "message": "unknown sign-in state"})
        try:
            user = await exchange(
                cfg.github_client_id, cfg.github_client_secret, code, f"{cfg.public_url}/auth/callback"
            )
        except gh.SignInError as exc:
            log.warning("GitHub sign-in failed: %s", exc)
            raise HTTPException(
                400, detail={"error": "invalid", "message": f"GitHub sign-in failed ({exc}); sign in again"}
            ) from None
        me = await user.me()
        token = user.token
        with db() as s, s.begin():
            dev = s.scalar(select(Developer).where(Developer.github_id == int(me["id"])))
            if dev is None:
                dev = Developer(github_id=int(me["id"]), github_login=me["login"])
                s.add(dev)
            dev.github_login = me["login"]
            dev.last_seen_at = datetime.now(UTC)
            s.flush()
            dev_id = str(dev.id)
        sid = store.create(dev_id, int(me["id"]), me["login"], token)
        resp = RedirectResponse("/me", status_code=303)
        secure = cfg.public_url.startswith("https://")
        resp.set_cookie(
            COOKIE, sid, httponly=True, secure=secure, samesite="lax", max_age=cfg.session_ttl_seconds
        )
        return resp

    @app.post("/auth/logout")
    def logout(request: Request) -> RedirectResponse:
        store.drop(request.cookies.get(COOKIE))
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Any:
        if store.get(request.cookies.get(COOKIE)):
            return RedirectResponse("/me", status_code=303)
        return TEMPLATES.TemplateResponse(request, "index.html", {})

    # ------------------------------------------------------------------ me
    def _active_credential(s: Session, dev_id: str) -> GatewayCredential | None:
        return credentials.active_credential(s, uuid.UUID(dev_id))

    async def _profile(who: SessionData) -> dict[str, Any]:
        roles = await access.roles(who)
        with engine.connect() as conn:
            led = [
                r.slug
                for r in conn.execute(
                    text("SELECT slug FROM team WHERE id = ANY(:t) ORDER BY slug"), {"t": list(roles.lead_of)}
                )
            ]
        return {"roles": roles.names, "is_admin": roles.admin, "lead_teams": led}

    @app.get("/me", response_class=HTMLResponse)
    async def me(request: Request, who: SessionData = Depends(current)) -> Any:
        with db() as s:
            cred = _active_credential(s, who.developer_id)
        return TEMPLATES.TemplateResponse(
            request,
            "me.html",
            {
                "who": who,
                "cred": cred,
                "gateway": cfg.gateway_type,
                "issued_key": None,
                **await _profile(who),
            },
        )

    @app.get("/api/me")
    async def api_me(who: SessionData = Depends(current)) -> dict[str, Any]:
        with db() as s:
            cred = _active_credential(s, who.developer_id)
        profile = await _profile(who)
        return {
            "github_login": who.github_login,
            "github_id": who.github_id,
            "roles": profile["roles"],
            "lead_teams": profile["lead_teams"],
            "credential": {"id": str(cred.id), "issued_at": cred.issued_at.isoformat()} if cred else None,
        }

    @app.get("/me/setup", response_class=HTMLResponse)
    def setup(request: Request, who: SessionData = Depends(current)) -> Any:
        tools = [{**t, "set": t["set"].format(url=cfg.gateway_public_url)} for t in TOOLS]
        return TEMPLATES.TemplateResponse(
            request, "setup.html", {"who": who, "tools": tools, "gateway_url": cfg.gateway_public_url}
        )

    # ------------------------------------------------------------------ credentials (T049)
    def _revoke(s: Session, cred: GatewayCredential) -> None:
        credentials.revoke(s, backend, cfg.gateway_type, cred)

    @app.post("/me/credential", response_class=HTMLResponse)
    async def issue_credential(request: Request, who: SessionData = Depends(current)) -> Any:
        cred, key = await asyncio.to_thread(
            credentials.issue, engine, backend, cfg.gateway_type, uuid.UUID(who.developer_id), who.github_id
        )
        # The key is shown exactly once and never stored or logged.
        return TEMPLATES.TemplateResponse(
            request,
            "me.html",
            {"who": who, "cred": cred, "gateway": cfg.gateway_type, "issued_key": key, **await _profile(who)},
        )

    @app.post("/me/credential/revoke")
    def revoke_credential(who: SessionData = Depends(current)) -> RedirectResponse:
        with db() as s, s.begin():
            cred = _active_credential(s, who.developer_id)
            if cred is not None:
                _revoke(s, cred)
        sync_keys()
        return RedirectResponse("/me", status_code=303)

    @app.delete("/me/credential")
    @app.delete("/api/me/credential")
    def api_revoke(who: SessionData = Depends(current)) -> JSONResponse:
        revoke_credential(who)
        return JSONResponse({"status": "revoked"})

    # ------------------------------------------------------------------ per-line results (T051)
    @app.get("/changes/{owner}/{repo}/{pr}", response_class=HTMLResponse)
    async def change(
        owner: str, repo: str, pr: int, request: Request, who: SessionData = Depends(current)
    ) -> Any:
        if not await user_client(who.token).can_view_repo(owner, repo):
            raise HTTPException(403, detail={"error": "forbidden", "message": "no access to this repository"})
        with engine.connect() as conn:
            head = conn.execute(
                LATEST_HEAD_SQL,
                {"fn": f"{owner}/{repo}", "pr": pr},
            ).first()
            if head is None:
                raise HTTPException(404, detail={"error": "not_found", "message": "no attribution yet"})
            lines = conn.execute(
                LINES_SQL,
                {"h": head.id},
            ).fetchall()
        return TEMPLATES.TemplateResponse(
            request,
            "changes.html",
            {"who": who, "owner": owner, "repo": repo, "pr": pr, "head": head, "lines": lines},
        )

    require_admin = access.admin_dependency(current)
    app.include_router(
        admin.create_router(engine, cfg, backend, require_admin, user_client, TEMPLATES, key_secret)
    )
    app.include_router(admin_roles.create_router(engine, require_admin, TEMPLATES))
    app.include_router(admin_teams.create_router(engine, require_admin, TEMPLATES))
    app.include_router(admin_settings.create_router(engine, require_admin, TEMPLATES))
    app.include_router(developers.create_router(engine, access, current, TEMPLATES))
    app.include_router(coverage.create_router(engine, cfg, access, current, user_client, TEMPLATES))

    return app
