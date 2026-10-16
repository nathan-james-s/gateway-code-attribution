"""T046-T047: ingest stores fingerprints idempotently, resolves credentials, sweeps stale instances."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core import messages
from gca_core.db.base import i32_to_u32
from gca_core.watermark import current_watermark
from gca_ingest.store import handle, mark_stale_instances
from gcattr import CapturedToolOutput, FingerprintKey, extract

KEY = FingerprintKey(1, b"\x42" * 32)


def _env(iid: str, seq: int, sent: datetime | None = None) -> dict:
    return {
        "schema": "gca.capture.v2",
        "instance_id": iid,
        "seq": seq,
        "gateway_type": "agentgateway",
        "sent_at": (sent or datetime.now(UTC)).isoformat(),
    }


def _developer_with_credential(conn) -> tuple[uuid.UUID, uuid.UUID]:  # type: ignore[no-untyped-def]
    dev = conn.execute(
        text(
            "INSERT INTO developer (id, github_id, github_login) VALUES (gen_random_uuid(), "
            "(random()*1e9)::bigint, 'alice') RETURNING id"
        )
    ).scalar()
    cred = conn.execute(
        text(
            "INSERT INTO gateway_credential (id, developer_id, gateway_type, key_hash, status) "
            "VALUES (gen_random_uuid(), :d, 'agentgateway', :h, 'active') RETURNING id"
        ),
        {"d": dev, "h": "sha256:" + uuid.uuid4().hex * 2},
    ).scalar()
    return dev, cred


def _event(iid: str, seq: int, cred: str | None) -> dict:
    out = CapturedToolOutput(
        "anthropic_messages",
        "Write",
        "json_args",
        {"file_path": "/r/src/app.py", "content": "x = compute(a, b)\ny = other(c)\n"},
        True,
    )
    body = messages.event_body(
        api_format="anthropic_messages",
        model="m",
        received_at=datetime.now(UTC).isoformat(),
        status="captured",
        alg=1,
        key_gen=1,
        lines=extract(out, KEY, 1),
        tool_call_count=1,
        credential_id=cred,
    )
    return messages.validate({**_env(iid, seq), **body})


def test_event_lines_bands_and_idempotency(pg_engine: Engine) -> None:
    iid = str(uuid.uuid4())
    with pg_engine.begin() as conn:
        dev, cred = _developer_with_credential(conn)
        msg = _event(iid, 0, str(cred))
        handle(conn, msg)
        handle(conn, msg)  # duplicate delivery
        rows = conn.execute(
            text(
                "SELECT minhash, path_suffix_fps, exact_fp FROM captured_line "
                "WHERE developer_id = :d ORDER BY line_ordinal"
            ),
            {"d": dev},
        ).fetchall()
        assert len(rows) == 2
        fps = extract(
            CapturedToolOutput(
                "anthropic_messages",
                "Write",
                "json_args",
                {"file_path": "/r/src/app.py", "content": "x = compute(a, b)\ny = other(c)\n"},
                True,
            ),
            KEY,
            1,
        )
        assert i32_to_u32(rows[0].minhash) == fps[0].minhash
        assert bytes(rows[0].exact_fp) == fps[0].exact_fp and len(rows[0].path_suffix_fps) == 3
        assert (
            conn.execute(text("SELECT count(*) FROM lsh_band WHERE developer_id = :d"), {"d": dev}).scalar()
            == 16
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM capture_event WHERE instance_id = :i"), {"i": uuid.UUID(iid)}
            ).scalar()
            == 1
        )


def test_unknown_credential_is_counted_not_stored(pg_engine: Engine) -> None:
    iid = str(uuid.uuid4())
    with pg_engine.begin() as conn:
        handle(conn, _event(iid, 0, str(uuid.uuid4())))
        ev = conn.execute(
            text("SELECT developer_id, line_count FROM capture_event WHERE instance_id = :i"),
            {"i": uuid.UUID(iid)},
        ).first()
        assert ev.developer_id is None and ev.line_count == 0
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM capture_loss WHERE instance_id = :i AND "
                    "cause = 'unknown_credential'"
                ),
                {"i": uuid.UUID(iid)},
            ).scalar()
            == 1
        )


def test_failure_message_becomes_capture_loss(pg_engine: Engine) -> None:
    iid = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    msg = messages.validate(
        {
            **_env(iid, 0),
            **messages.failure_body(
                cause="truncated", count=2, period_start=now, period_end=now, api_format="openai_chat"
            ),
        }
    )
    with pg_engine.begin() as conn:
        handle(conn, msg)
        assert (
            conn.execute(
                text("SELECT count FROM capture_loss WHERE instance_id = :i"), {"i": uuid.UUID(iid)}
            ).scalar()
            == 2
        )


def test_watermark_and_stale_sweeper(pg_engine: Engine) -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    old = datetime.now(UTC) - timedelta(minutes=5)
    with pg_engine.begin() as conn:
        conn.execute(text("UPDATE capture_instance SET status = 'closed'"))  # isolate from other tests
        handle(
            conn,
            messages.validate({**_env(a, 0), **messages.heartbeat_body(responses_seen=0, buffer_depth=0)}),
        )
        handle(
            conn,
            messages.validate(
                {**_env(b, 0, sent=old), **messages.heartbeat_body(responses_seen=0, buffer_depth=0)}
            ),
        )
        assert current_watermark(conn) == old  # the oldest active instance holds the watermark back
        assert mark_stale_instances(conn) == 1  # b has not heartbeated for > 15 s
        wm = current_watermark(conn)
        assert wm is not None and wm > old  # a stale instance never freezes the watermark (U1)
        handle(
            conn,
            messages.validate(
                {
                    **_env(a, 1),
                    **messages.heartbeat_body(responses_seen=0, buffer_depth=0, shutting_down=True),
                }
            ),
        )
        assert (
            conn.execute(
                text("SELECT status FROM capture_instance WHERE instance_id = :i"), {"i": uuid.UUID(a)}
            ).scalar()
            == "closed"
        )
        assert current_watermark(conn) is None


def _parts(iid: str, first_seq: int, cred: str | None, n_lines: int, max_bytes: int) -> list[dict]:
    content = "".join(f"value_{i} = compute(item_{i}, factor={i})\n" for i in range(n_lines))
    out = CapturedToolOutput(
        "anthropic_messages", "Write", "json_args", {"file_path": "/r/src/big.py", "content": content}, True
    )
    body = messages.event_body(
        api_format="anthropic_messages",
        model="m",
        received_at=datetime.now(UTC).isoformat(),
        status="captured",
        alg=1,
        key_gen=1,
        lines=extract(out, KEY, 1),
        tool_call_count=1,
        credential_id=cred,
    )
    return [
        messages.validate({**_env(iid, first_seq + k), **part})
        for k, part in enumerate(messages.event_parts(body, max_bytes))
    ]


def test_an_event_sent_in_parts_is_one_event(pg_engine: Engine) -> None:
    iid = str(uuid.uuid4())
    with pg_engine.begin() as conn:
        dev, cred = _developer_with_credential(conn)
        parts = _parts(iid, 0, str(cred), 40, 12_000)
        assert len(parts) >= 3
        for part in [*parts, parts[1]]:  # the second part is delivered twice
            handle(conn, part)
        events = conn.execute(
            text("SELECT id, line_count FROM capture_event WHERE developer_id = :d"), {"d": dev}
        ).fetchall()
        assert [(str(e.id), e.line_count) for e in events] == [(parts[0]["event_id"], 40)]
        lines = conn.execute(
            text("SELECT count(*), count(DISTINCT line_ordinal) FROM captured_line WHERE developer_id = :d"),
            {"d": dev},
        ).one()
        assert tuple(lines) == (40, 40)
        bands = conn.execute(
            text("SELECT count(*) FROM lsh_band WHERE developer_id = :d"), {"d": dev}
        ).scalar()
        assert bands == 40 * 8


def test_unknown_credential_in_parts_is_counted_once(pg_engine: Engine) -> None:
    iid = str(uuid.uuid4())
    with pg_engine.begin() as conn:
        for part in _parts(iid, 0, str(uuid.uuid4()), 40, 12_000):
            handle(conn, part)
        n = conn.execute(
            text(
                "SELECT coalesce(sum(count), 0) FROM capture_loss "
                "WHERE instance_id = :i AND cause = 'unknown_credential'"
            ),
            {"i": uuid.UUID(iid)},
        ).scalar()
        assert n == 1
