"""JetStream access and the bounded, never-blocking capture publisher (research R12, R13; FR-005a).

Sequence numbers are assigned when a message is *sent*, not when it is queued. A message dropped from a full
buffer therefore never creates a sequence gap; it is counted once, as ``buffer_overflow``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Callable
from typing import Any, Protocol

from . import messages

__all__ = ["STREAM", "SUBJECT_PREFIX", "BufferedPublisher", "Sender", "connect_jetstream", "ensure_stream"]

log = logging.getLogger(__name__)

STREAM = "GCA_CAPTURE"
SUBJECT_PREFIX = "gca.capture"


class Sender(Protocol):
    async def __call__(self, subject: str, payload: bytes) -> None: ...


async def connect_jetstream(url: str) -> tuple[Any, Any]:
    import nats

    nc = await nats.connect(url, max_reconnect_attempts=-1, reconnect_time_wait=1)
    return nc, nc.jetstream()


async def ensure_stream(js: Any) -> None:
    from nats.js.api import RetentionPolicy, StorageType, StreamConfig

    cfg = StreamConfig(
        name=STREAM,
        subjects=[f"{SUBJECT_PREFIX}.>"],
        storage=StorageType.FILE,
        retention=RetentionPolicy.WORK_QUEUE,
    )
    try:
        await js.add_stream(cfg)
    except Exception:  # already exists with a compatible config
        await js.update_stream(cfg)


class BufferedPublisher:
    """In-memory FIFO (default 10,000 messages) drained by a background task with retry.

    ``enqueue`` never blocks and never raises. On overflow the oldest queued *event* is dropped and counted;
    ``take_overflow()`` hands that count to the caller, which reports it as a ``buffer_overflow`` failure.
    """

    def __init__(
        self,
        send: Sender,
        *,
        subject: str,
        envelope: Callable[[int], dict[str, Any]],
        max_buffer: int = 10_000,
        retry_seconds: float = 0.5,
    ) -> None:
        self._send = send
        self._subject = subject
        self._envelope = envelope
        self._max = max_buffer
        self._retry = retry_seconds
        self._q: deque[dict[str, Any]] = deque()
        self._wake = asyncio.Event()
        self._overflow = 0
        self._seq = 0
        self._task: asyncio.Task[None] | None = None
        self.connected = False

    @property
    def depth(self) -> int:
        return len(self._q)

    @property
    def next_seq(self) -> int:
        return self._seq

    def take_overflow(self) -> int:
        n, self._overflow = self._overflow, 0
        return n

    def enqueue(self, body: dict[str, Any]) -> None:
        if len(self._q) >= self._max:
            # Drop the oldest event first, then the oldest heartbeat; a failure report only as a last resort.
            for kind in ("event", "heartbeat"):
                idx = next((i for i, queued in enumerate(self._q) if queued.get("kind") == kind), None)
                if idx is not None:
                    del self._q[idx]
                    if kind == "event":
                        self._overflow += 1
                    break
            else:
                self._q.popleft()
                self._overflow += 1
        self._q.append(body)
        self._wake.set()

    async def _publish(self, body: dict[str, Any]) -> None:
        msg = {**self._envelope(self._seq), **body}
        await self._send(self._subject, messages.encode(msg))
        self._seq += 1

    async def send_now(self, body: dict[str, Any]) -> bool:
        """Publish immediately (used for heartbeats). Returns False instead of raising."""
        try:
            await self._publish(body)
        except Exception:
            self.connected = False
            return False
        self.connected = True
        return True

    async def run(self) -> None:
        while True:
            if not self._q:
                self._wake.clear()
                await self._wake.wait()
                continue
            body = self._q[0]
            try:
                await self._publish(body)
            except messages.MessageError:
                log.exception("dropping a message that fails the capture schema")
                self._q.popleft()
                self._overflow += 1
                continue
            except Exception:
                self.connected = False
                await asyncio.sleep(self._retry)
                continue
            self.connected = True
            self._q.popleft()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self.run())

    async def drain(self, timeout: float = 5.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while self._q and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
