"""Ingest stops promptly on SIGTERM. It runs as PID 1, where an unhandled SIGTERM is ignored: without a handler it
kept consuming until Kubernetes killed it 30 s later, so "scaled to zero" didn't pause capture."""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

import pytest

from gca_ingest import __main__ as entry
from gca_ingest import consumer


class _Msg:
    def __init__(self, n: int) -> None:
        self.n = n


class _Sub:
    def __init__(self, batches: list[list[_Msg]]) -> None:
        self.batches = batches

    async def fetch(self, batch: int, timeout: float) -> list[_Msg]:
        if not self.batches:
            await asyncio.sleep(timeout)
            raise TimeoutError
        return self.batches.pop(0)


class _Conn:
    closed = False

    async def close(self) -> None:
        self.closed = True


async def test_consume_stops_between_messages_and_leaves_the_rest_for_redelivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sub, conn, stop = _Sub([[_Msg(1), _Msg(2), _Msg(3)]]), _Conn(), asyncio.Event()

    class _JS:
        async def pull_subscribe(self, *a: Any, **kw: Any) -> _Sub:
            return sub

    async def connect(url: str) -> tuple[_Conn, _JS]:
        return conn, _JS()

    async def ensure(js: Any) -> None:
        return None

    processed: list[int] = []

    async def process(engine: Any, m: _Msg) -> None:
        processed.append(m.n)
        stop.set()  # SIGTERM arrives while the first message is being stored

    monkeypatch.setattr(consumer, "connect_jetstream", connect)
    monkeypatch.setattr(consumer, "ensure_stream", ensure)
    monkeypatch.setattr(consumer, "_process", process)
    await asyncio.wait_for(consumer.consume(None, "nats://x", stop=stop), 5)  # type: ignore[arg-type]
    assert processed == [1]  # 2 and 3 stay unacked: JetStream redelivers them to the next ingest
    assert conn.closed


async def test_sigterm_ends_ingest_promptly(monkeypatch: pytest.MonkeyPatch) -> None:
    async def consume(engine: Any, url: str, *, stop: asyncio.Event) -> None:
        await stop.wait()

    async def maintenance(engine: Any, gateway: str) -> None:
        await asyncio.Event().wait()  # runs until cancelled

    class _Cfg:
        nats_url, gateway_type = "nats://x", "litellm"

    monkeypatch.setattr(entry, "consume", consume)
    monkeypatch.setattr(entry, "maintenance", maintenance)
    monkeypatch.setattr(entry, "settings", lambda: _Cfg())
    monkeypatch.setattr(entry, "engine", lambda: None)
    asyncio.get_running_loop().call_later(0.1, os.kill, os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(entry._main(), 5)
