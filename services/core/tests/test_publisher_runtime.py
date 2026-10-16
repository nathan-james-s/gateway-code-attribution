"""BufferedPublisher and CaptureRuntime: never block, never raise, count every loss once."""

from __future__ import annotations

import asyncio
import json

from gca_core import messages
from gca_core.capture_runtime import CaptureRuntime
from gca_core.nats import BufferedPublisher


class FlakySender:
    def __init__(self, fail_first: int = 0) -> None:
        self.sent: list[dict] = []
        self.fail_first = fail_first

    async def __call__(self, subject: str, payload: bytes) -> None:
        if self.fail_first > 0:
            self.fail_first -= 1
            raise ConnectionError("nats down")
        self.sent.append(json.loads(payload))


def _env(seq: int) -> dict:
    return {
        "schema": "gca.capture.v2",
        "instance_id": "8f1c1b0e-6a4c-4b31-9d1f-3a0f8a2a1c11",
        "seq": seq,
        "gateway_type": "litellm",
        "sent_at": messages.now_iso(),
    }


def _hb(n: int) -> dict:
    return messages.heartbeat_body(responses_seen=n, buffer_depth=0)


def _ev(n: int) -> dict:
    return messages.event_body(
        api_format="openai_chat",
        model=f"m{n}",
        received_at=messages.now_iso(),
        status="captured",
        alg=1,
        key_gen=1,
        lines=[],
        tool_call_count=0,
    )


async def test_seq_assigned_at_send_and_overflow_counted_once() -> None:
    sender = FlakySender()
    pub = BufferedPublisher(sender, subject="gca.capture.litellm", envelope=_env, max_buffer=3)
    for i in range(5):
        pub.enqueue(_ev(i))
    assert pub.take_overflow() == 2
    pub.start()
    await pub.drain()
    await pub.stop()
    assert [m["seq"] for m in sender.sent] == [0, 1, 2]  # no gaps: dropped messages never got a seq
    assert [m["model"] for m in sender.sent] == ["m2", "m3", "m4"]


async def test_heartbeats_dropped_before_failures_and_not_counted_as_loss() -> None:
    pub = BufferedPublisher(FlakySender(), subject="s", envelope=_env, max_buffer=2)
    now = messages.now_iso()
    pub.enqueue(_hb(1))
    pub.enqueue(messages.failure_body(cause="truncated", count=1, period_start=now, period_end=now))
    pub.enqueue(_hb(2))
    assert pub.take_overflow() == 0
    assert [m["kind"] for m in pub._q] == ["failure", "heartbeat"]


async def test_overflow_drops_oldest_event_before_failure_reports() -> None:
    pub = BufferedPublisher(FlakySender(), subject="s", envelope=_env, max_buffer=2)
    now = messages.now_iso()
    pub.enqueue(messages.failure_body(cause="truncated", count=1, period_start=now, period_end=now))
    pub.enqueue({"kind": "event", "marker": 1})
    pub.enqueue(messages.failure_body(cause="unparsable", count=1, period_start=now, period_end=now))
    kinds = [m.get("cause", m.get("kind")) for m in pub._q]
    assert kinds == ["truncated", "unparsable"]


async def test_retries_until_nats_returns() -> None:
    sender = FlakySender(fail_first=3)
    pub = BufferedPublisher(sender, subject="s", envelope=_env, retry_seconds=0.01)
    pub.enqueue(_hb(1))
    pub.start()
    await pub.drain(timeout=2)
    await pub.stop()
    assert len(sender.sent) == 1 and sender.sent[0]["seq"] == 0


async def test_runtime_emitters_never_raise_and_heartbeat_reports_overflow() -> None:
    sender = FlakySender()
    rt = CaptureRuntime("litellm", sender, heartbeat_seconds=0.05, max_buffer=2)
    for _ in range(3):  # three events into a 2-slot buffer -> one event dropped and counted
        rt.emit_event(api_format="openai_chat", model="m", lines=[], tool_call_count=0, alg=1, key_gen=1)
    rt.emit_event(
        api_format="openai_chat",
        model="m",
        lines=[],
        tool_call_count=0,
        alg=1,
        key_gen=1,
        received_at="not-a-date",
    )  # invalid -> schema rejects at send; must not raise here
    rt.start()
    await asyncio.sleep(0.3)
    await rt.shutdown()
    kinds = [(m["kind"], m.get("cause")) for m in sender.sent]
    assert ("failure", "buffer_overflow") in kinds
    assert kinds[-1] == ("heartbeat", None) and sender.sent[-1]["shutting_down"] is True


def _fps(n: int) -> list:
    import os
    import random

    from gcattr import LineFingerprint

    rng = random.Random(n)
    return [
        LineFingerprint(
            os.urandom(16),
            tuple(rng.getrandbits(32) for _ in range(128)),
            tuple(os.urandom(8) for _ in range(8)),
            (os.urandom(16),),
            1,
            i,
            1,
            1,
        )
        for i in range(1, n + 1)
    ]


class LimitedSender(FlakySender):
    """Like NATS: refuses any payload over max_payload, whatever happens after."""

    def __init__(self, max_payload: int) -> None:
        super().__init__()
        self.max_payload = max_payload

    async def __call__(self, subject: str, payload: bytes) -> None:
        if len(payload) > self.max_payload:
            from nats.errors import MaxPayloadError

            raise MaxPayloadError
        await super().__call__(subject, payload)


async def test_a_large_response_is_sent_in_parts_of_one_event() -> None:
    sender = LimitedSender(1_048_576)
    rt = CaptureRuntime("litellm", sender, heartbeat_seconds=3600)
    rt.start()
    lines = _fps(3000)  # about 2.7 MB of fingerprints
    rt.emit_event(api_format="openai_chat", model="m", lines=lines, tool_call_count=1, alg=1, key_gen=1)
    await rt.publisher.drain()
    events = [m for m in sender.sent if m["kind"] == "event"]
    assert len(events) >= 3 and len({e["event_id"] for e in events}) == 1
    assert [e["part"] for e in events] == [
        {"index": i, "count": len(events)} for i in range(1, len(events) + 1)
    ]
    assert sum(len(e["lines"]) for e in events) == 3000
    assert [messages.line_from_wire(w)["minhash"] for e in events for w in e["lines"]] == [
        f.minhash for f in lines
    ]
    assert rt.responses_seen == 1
    await rt.publisher.stop()


async def test_a_message_the_server_refuses_is_dropped_and_counted_without_blocking() -> None:
    sender = LimitedSender(2_000)
    pub = BufferedPublisher(sender, subject="gca.capture.litellm", envelope=_env)
    big = messages.event_body(
        api_format="openai_chat",
        model="m",
        received_at=messages.now_iso(),
        status="captured",
        alg=1,
        key_gen=1,
        lines=_fps(5),
        tool_call_count=1,
    )
    pub.enqueue(big)
    pub.enqueue(_ev(1))
    pub.enqueue(_hb(1))
    pub.start()
    await pub.drain(timeout=2)
    await pub.stop()
    assert [m["kind"] for m in sender.sent] == ["event", "heartbeat"]  # what came after it still went out
    assert pub.take_unsendable() == 1 and pub.take_overflow() == 0
    assert [m["seq"] for m in sender.sent] == [
        0,
        1,
    ]  # no sequence gap: it's reported as publish_failed instead


async def test_a_refused_message_is_reported_as_publish_failed() -> None:
    sender = LimitedSender(2_000)
    rt = CaptureRuntime("litellm", sender, heartbeat_seconds=0.05, max_message_bytes=10_000_000)
    rt.start()
    rt.emit_event(api_format="openai_chat", model="m", lines=_fps(5), tool_call_count=1, alg=1, key_gen=1)
    await asyncio.sleep(0.4)
    await rt.publisher.stop()
    failures = [m for m in sender.sent if m["kind"] == "failure"]
    assert [(f["cause"], f["count"]) for f in failures] == [("publish_failed", 1)]
