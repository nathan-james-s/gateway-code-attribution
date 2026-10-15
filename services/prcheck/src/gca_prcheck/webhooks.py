"""GitHub webhook delivery (T069, T071; contracts/github-app.md "Delivery modes"; FR-018, FR-020).

Verifies `X-Hub-Signature-256` with the App's webhook secret and handles each `X-GitHub-Delivery` once. Every
handler is idempotent too, so a redelivery racing its first delivery is still harmless. Payloads carry no code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core.github import AppClient

from . import events
from .checkrun import CHECK_NAME
from .polling import announce, needs_announce, record_head, upsert_repository

log = logging.getLogger("gca.prcheck.webhooks")

__all__ = ["create_router", "signature_ok"]


def signature_ok(secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def _seen(engine: Engine, delivery: str) -> bool:
    with engine.connect() as conn:
        return (
            conn.execute(text("SELECT 1 FROM webhook_delivery WHERE id = :d"), {"d": delivery}).first()
            is not None
        )


def _remember(engine: Engine, delivery: str, event: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO webhook_delivery (id, event) VALUES (:d, :e) ON CONFLICT (id) DO NOTHING"),
            {"d": delivery, "e": event},
        )


def create_router(engine: Engine, gh: AppClient, secret: str) -> APIRouter:
    router = APIRouter()

    async def on_pull_request(payload: dict[str, Any], background: BackgroundTasks) -> None:
        action, pr, repo = payload.get("action"), payload["pull_request"], payload["repository"]
        inst = int(payload["installation"]["id"])
        repo_id = upsert_repository(engine, repo, inst)
        if action in ("opened", "synchronize", "reopened"):
            if action == "reopened":
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE change SET state = 'open', merged_at = NULL WHERE repository_id = :r "
                            "AND pr_number = :pr AND state = 'closed'"
                        ),
                        {"r": repo_id, "pr": pr["number"]},
                    )
            head_id = record_head(engine, repo_id, pr)  # a new head; earlier heads keep their results
            if head_id is not None:
                background.add_task(announce, engine, gh, head_id, inst, repo["full_name"], pr["head"]["sha"])
        elif action == "closed":
            final_id = events.on_closed(engine, repo_id, pr)
            if final_id is not None and needs_announce(engine, final_id):
                background.add_task(
                    announce, engine, gh, final_id, inst, repo["full_name"], pr["head"]["sha"]
                )

    def on_check_run(payload: dict[str, Any]) -> None:
        run = payload["check_run"]
        if payload.get("action") == "rerequested" and run.get("name") == CHECK_NAME:
            events.rerun_head(engine, payload["repository"]["full_name"], run["head_sha"])

    def on_installation_repositories(payload: dict[str, Any]) -> None:
        inst = int(payload["installation"]["id"])
        for repo in payload.get("repositories_added") or []:
            upsert_repository(engine, repo, inst)
        removed = [int(r["id"]) for r in payload.get("repositories_removed") or []]
        if removed:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE repository SET active = false WHERE github_id = ANY(:ids)"), {"ids": removed}
                )

    def on_installation(payload: dict[str, Any]) -> None:
        if payload.get("action") in ("deleted", "suspend"):
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE repository SET active = false WHERE installation_id = :i"),
                    {"i": int(payload["installation"]["id"])},
                )

    @router.post("/webhooks/github")
    async def github(request: Request, background: BackgroundTasks) -> JSONResponse:
        body = await request.body()
        if not signature_ok(secret, body, request.headers.get("x-hub-signature-256")):
            raise HTTPException(401, detail={"error": "unauthenticated", "message": "bad webhook signature"})
        delivery = request.headers.get("x-github-delivery", "")
        event = request.headers.get("x-github-event", "")
        if not delivery:
            raise HTTPException(400, detail={"error": "invalid", "message": "missing X-GitHub-Delivery"})
        if _seen(engine, delivery):
            return JSONResponse({"status": "duplicate"}, status_code=200)
        payload = json.loads(body)
        if event == "pull_request":
            await on_pull_request(payload, background)
        elif event == "check_run":
            on_check_run(payload)
        elif event == "installation_repositories":
            on_installation_repositories(payload)
        elif event == "installation":
            on_installation(payload)
        # membership, team and organization events drive roles (US3); accepted and ignored for now.
        _remember(engine, delivery, event)
        return JSONResponse({"status": "accepted"}, status_code=202)

    return router
