"""PR check service: health endpoints plus the polling and attribution loops (webhooks arrive in T071)."""

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

from . import polling, webhooks, worker
from .config import PrcheckConfig

log = logging.getLogger("gca.prcheck")


def create_app(engine: Engine, cfg: PrcheckConfig, gh: AppClient, keys: KeyRing) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        tasks = [asyncio.create_task(worker.run(engine, gh, keys, cfg))]
        if cfg.delivery == "polling":
            tasks.append(asyncio.create_task(polling.run(engine, gh, cfg.poll_seconds)))
        log.info("prcheck started (delivery=%s)", cfg.delivery)
        yield
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t

    app = FastAPI(title="Gateway Code Attribution PR check", docs_url=None, redoc_url=None, lifespan=lifespan)
    if cfg.delivery == "webhook":
        app.include_router(webhooks.create_router(engine, gh, cfg.webhook_secret))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app
