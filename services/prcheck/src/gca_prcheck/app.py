"""PR check service: health endpoints, the polling and attribution loops, webhooks, and team sync (T082)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core.github import AppClient
from gca_core.keys import KeyRing

from . import polling, teamsync, webhooks, worker
from .config import PrcheckConfig

log = logging.getLogger("gca.prcheck")


def create_app(engine: Engine, cfg: PrcheckConfig, gh: AppClient, keys: KeyRing) -> FastAPI:
    teams = teamsync.TeamSync(engine, gh, cfg.github_org) if cfg.github_org else None

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(worker.run(engine, gh, keys, cfg))]
        if cfg.delivery == "polling":
            tasks.append(asyncio.create_task(polling.run(engine, gh, cfg.poll_seconds)))
        if teams is not None:
            tasks.append(asyncio.create_task(teams.run()))
        log.info("prcheck started (delivery=%s)", cfg.delivery)
        yield
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t

    app = FastAPI(title="Gateway Code Attribution PR check", docs_url=None, redoc_url=None, lifespan=lifespan)
    if cfg.delivery == "webhook":
        app.include_router(
            webhooks.create_router(
                engine, gh, cfg.webhook_secret, on_team_event=teams.request if teams else None
            )
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app
