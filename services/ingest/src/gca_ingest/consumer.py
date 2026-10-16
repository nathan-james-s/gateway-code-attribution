"""JetStream pull consumer: validate, store, then ack (T046). Run ONE replica: order per instance matters."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core import messages
from gca_core.nats import STREAM, SUBJECT_PREFIX, connect_jetstream, ensure_stream

from .loss import sweep
from .maintenance import daily
from .store import handle

log = logging.getLogger("gca.ingest")

DURABLE = "gca-ingest"


async def consume(
    engine: Engine, nats_url: str, *, batch: int = 100, stop: asyncio.Event | None = None
) -> None:
    """Consume until ``stop`` is set. It's checked between messages: fetched messages not yet stored stay unacked,
    and JetStream redelivers them to the next ingest."""
    stop = stop or asyncio.Event()
    nc, js = await connect_jetstream(nats_url)
    try:
        await ensure_stream(js)
        sub = await js.pull_subscribe(f"{SUBJECT_PREFIX}.>", durable=DURABLE, stream=STREAM)
        while not stop.is_set():
            try:
                msgs = await sub.fetch(batch, timeout=1)
            except TimeoutError:
                continue
            except Exception:
                log.exception("fetch failed")
                await asyncio.sleep(1)
                continue
            for m in msgs:
                if stop.is_set():
                    break
                await _process(engine, m)
    finally:
        await nc.close()


async def _process(engine: Engine, m: Any) -> None:
    try:
        msg = messages.decode(m.data)
    except messages.MessageError as exc:
        log.error("rejecting a message that fails the capture contract: %s", exc)  # never logs the payload
        await m.term()
        return
    try:
        await asyncio.to_thread(_store, engine, msg)
    except Exception:
        log.exception("store failed; message will be redelivered")
        await m.nak(delay=2)
        return
    await m.ack()


def _store(engine: Engine, msg: dict[str, Any]) -> None:
    with engine.begin() as conn:
        handle(conn, msg)


async def maintenance(engine: Engine, gateway: str, *, sweep_seconds: float = 5.0) -> None:
    """Stale-instance and capture-loss sweeper every 5 s (U1, T088); partitions three days ahead at start and
    hourly; key expiry and retention daily (maintenance.daily)."""
    last_partition = last_daily = float("-inf")
    loop = asyncio.get_running_loop()
    while True:
        try:
            now = loop.time()
            with engine.begin() as conn:
                swept = sweep(conn, gateway)
                if swept["stale"] or swept["outages"]:
                    log.warning("capture loss: %s", swept)
                if now - last_partition > 3600:
                    conn.execute(text("SELECT gca_ensure_partitions(3)"))
                    last_partition = now
                if now - last_daily > 86400:
                    log.info("daily maintenance: %s", daily(conn))
                    last_daily = now
        except Exception:
            log.exception("maintenance failed")
        await asyncio.sleep(sweep_seconds)
