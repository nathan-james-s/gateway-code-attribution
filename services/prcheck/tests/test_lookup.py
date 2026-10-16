"""The PR check fetches only the captures a PR's lines can match, through the indexes (research R11), and gets
the same outcomes as with every capture in the matching window."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core import messages
from gca_ingest.store import handle
from gca_prcheck.worker import load_candidates, lookup_candidates
from gcattr import (
    AddedLine,
    CapturedToolOutput,
    FingerprintKey,
    attribute,
    extract,
    lookup_keys,
    select_candidates,
)

KEY = FingerprintKey(1, b"\x42" * 32)
WROTE = [
    "def subtotal(items):\n    return sum(i.price * i.qty for i in items)\n",
    "TAX = load_rates(region='EU', year=2026)\nresult = compute_total(order.items, discount=customer.discount)\n",
    "logger.info('processed %d orders for %s', len(orders), customer.name)\n",
]
UNRELATED = [
    "schedule.every(10).minutes.do(refresh_exchange_rates)\n",
    "parser.add_argument('--dry-run', action='store_true', help='print the plan only')\n",
]


def _developer(conn) -> tuple[uuid.UUID, int, uuid.UUID]:  # type: ignore[no-untyped-def]
    gid = int(uuid.uuid4().int % 1_000_000_000)
    dev = conn.execute(
        text(
            "INSERT INTO developer (id, github_id, github_login) VALUES (gen_random_uuid(), :g, 'ada') RETURNING id"
        ),
        {"g": gid},
    ).scalar()
    cred = conn.execute(
        text(
            "INSERT INTO gateway_credential (id, developer_id, gateway_type, key_hash, status) "
            "VALUES (gen_random_uuid(), :d, 'agentgateway', :h, 'active') RETURNING id"
        ),
        {"d": dev, "h": "sha256:" + uuid.uuid4().hex * 2},
    ).scalar()
    return dev, gid, cred


def _capture(conn, cred: uuid.UUID, seq: int, path: str, content: str) -> None:  # type: ignore[no-untyped-def]
    out = CapturedToolOutput(
        "anthropic_messages", "Write", "json_args", {"file_path": path, "content": content}, True
    )
    env = {
        "schema": messages.SCHEMA_ID,
        "instance_id": str(uuid.uuid5(uuid.NAMESPACE_URL, str(cred))),
        "seq": seq,
        "gateway_type": "agentgateway",
        "sent_at": datetime.now(UTC).isoformat(),
    }
    body = messages.event_body(
        api_format="anthropic_messages",
        model="m",
        received_at=datetime.now(UTC).isoformat(),
        status="captured",
        alg=1,
        key_gen=1,
        lines=extract(out, KEY, 1),
        tool_call_count=1,
        credential_id=str(cred),
    )
    handle(conn, messages.validate({**env, **body}))


def test_indexed_lookup_returns_the_selection_and_the_same_outcomes(pg_engine: Engine) -> None:
    with pg_engine.begin() as conn:
        dev, gid, cred = _developer(conn)
        for n, content in enumerate(WROTE):
            _capture(conn, cred, n, "/w/src/app.py", content)
        for n, content in enumerate(UNRELATED * 20, start=len(WROTE)):
            _capture(conn, cred, n, "/w/src/other.py", content)
        pr = [
            "def subtotal(items):",
            "    return sum(i.price * i.qty for i in items)",  # exact: anchors the first event
            "logger.info('processed %d orders for %s', len(orders), client.name)",  # edited
            "result = compute_total(",  # wrapped
            "    order.items,",
            "    discount=customer.discount,",
            ")",
            "metrics.increment('checkout.completed')",  # human
        ]
        lines = [AddedLine("src/app.py", n, t, gid) for n, t in enumerate(pr, 1)]
        now = datetime.now(UTC)
        since, until = now - timedelta(days=14), now + timedelta(minutes=1)
        lk = lookup_keys(lines, {1: KEY}, 1)[gid]

        fetched = lookup_candidates(conn, dev, since, until, lk)
        everything = load_candidates(conn, dev, since, until)

    def ids(cs):  # type: ignore[no-untyped-def]
        return sorted((c.capture_event_id, c.tool_call_ordinal, c.line_ordinal) for c in cs)

    assert ids(fetched) == ids(select_candidates(everything, lk))
    assert len(fetched) < len(everything) / 5  # the 40 unrelated captures aren't read
    got = attribute(lines, {gid: fetched}, {1: KEY}, 1)
    assert got == attribute(lines, {gid: everything}, {1: KEY}, 1)
    assert [o.outcome for o in got][:3] == ["ai_unmodified", "ai_unmodified", "ai_modified"]
    assert got[3].outcome == "ai_modified" and got[-1].outcome == "human"
