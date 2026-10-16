"""Shared capture runtime for both gateway adapters (research R12; FR-005, FR-005a).

Nothing here may raise into the gateway's request path: every method swallows and counts its own errors.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from gcattr import LineFingerprint

from . import messages
from .nats import SUBJECT_PREFIX, BufferedPublisher, Sender

__all__ = ["CaptureRuntime"]

log = logging.getLogger(__name__)


class CaptureRuntime:
    def __init__(
        self,
        gateway_type: str,
        send: Sender,
        *,
        heartbeat_seconds: float = 5.0,
        max_buffer: int = 10_000,
        max_message_bytes: int = 900_000,
    ) -> None:
        self.gateway_type = gateway_type
        self.instance_id = str(uuid.uuid4())
        self.heartbeat_seconds = heartbeat_seconds
        self.max_message_bytes = (
            max_message_bytes  # under NATS's default 1 MiB max_payload, with room to spare
        )
        self.responses_seen = 0
        self._internal_errors = 0
        self._started = datetime.now(UTC)
        self._publisher = BufferedPublisher(
            send,
            subject=f"{SUBJECT_PREFIX}.{gateway_type}",
            envelope=self._envelope,
            max_buffer=max_buffer,
        )
        self._hb_task: asyncio.Task[None] | None = None
        self._shutting_down = False

    # ------------------------------------------------------------------ lifecycle
    def _envelope(self, seq: int) -> dict[str, Any]:
        return {
            "schema": messages.SCHEMA_ID,
            "instance_id": self.instance_id,
            "seq": seq,
            "gateway_type": self.gateway_type,
            "sent_at": messages.now_iso(),
        }

    def start(self) -> None:
        self._publisher.start()
        if self._hb_task is None:
            self._hb_task = asyncio.get_running_loop().create_task(self._heartbeats())
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, self._on_sigterm)

    def _on_sigterm(self) -> None:
        asyncio.get_running_loop().create_task(self.shutdown())

    async def shutdown(self) -> None:
        self._shutting_down = True
        await self._publisher.drain()
        await self._publisher.send_now(
            messages.heartbeat_body(
                responses_seen=self.responses_seen, buffer_depth=self._publisher.depth, shutting_down=True
            )
        )
        if self._hb_task:
            self._hb_task.cancel()
        await self._publisher.stop()

    async def _heartbeats(self) -> None:
        while not self._shutting_down:
            try:
                now = messages.now_iso()
                for cause, count in (
                    ("buffer_overflow", self._publisher.take_overflow()),
                    ("publish_failed", self._take_internal_errors() + self._publisher.take_unsendable()),
                ):
                    if count:
                        self._publisher.enqueue(
                            messages.failure_body(cause=cause, count=count, period_start=now, period_end=now)
                        )
                # Heartbeats travel through the same FIFO as events: when ingest sees a heartbeat sent at
                # T, every event queued before T has already been ingested. That makes the watermark sound.
                self._publisher.enqueue(
                    messages.heartbeat_body(
                        responses_seen=self.responses_seen, buffer_depth=self._publisher.depth
                    )
                )
            except Exception:  # never let the heartbeat loop die
                log.exception("heartbeat failed")
            await asyncio.sleep(self.heartbeat_seconds)

    def _take_internal_errors(self) -> int:
        n, self._internal_errors = self._internal_errors, 0
        return n

    # ------------------------------------------------------------------ emitters (never raise)
    def emit_event(
        self,
        *,
        api_format: str,
        model: str,
        lines: Sequence[LineFingerprint],
        tool_call_count: int,
        alg: int,
        key_gen: int,
        status: str = "captured",
        failure_cause: str | None = None,
        credential_id: str | None = None,
        tool_hint: str | None = None,
        session_id: str | None = None,
        received_at: str | None = None,
    ) -> None:
        try:
            self.responses_seen += 1
            body = messages.event_body(
                api_format=api_format,
                model=model,
                received_at=received_at or messages.now_iso(),
                status=status,
                alg=alg,
                key_gen=key_gen,
                lines=list(lines),
                tool_call_count=tool_call_count,
                credential_id=credential_id,
                tool_hint=tool_hint,
                session_id=session_id,
                failure_cause=failure_cause,
            )
            for part in messages.event_parts(body, self.max_message_bytes):
                self._publisher.enqueue(part)
        except Exception:
            self._internal_errors += 1
            log.exception("emit_event failed")

    def emit_failure(
        self,
        cause: str,
        count: int = 1,
        *,
        credential_id: str | None = None,
        api_format: str | None = None,
        tool_hint: str | None = None,
        count_as_response: bool = True,
    ) -> None:
        try:
            if count_as_response:
                self.responses_seen += count
            now = messages.now_iso()
            self._publisher.enqueue(
                messages.failure_body(
                    cause=cause,
                    count=count,
                    period_start=now,
                    period_end=now,
                    credential_id=credential_id,
                    api_format=api_format,
                    tool_hint=tool_hint,
                )
            )
        except Exception:
            self._internal_errors += 1
            log.exception("emit_failure failed")

    @property
    def publisher(self) -> BufferedPublisher:
        return self._publisher
