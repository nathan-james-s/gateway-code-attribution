"""Migration 0001 and data-model constraints, on a real PostgreSQL 17 (T030; data-model.md)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gca_core.db.models_identity import Developer, IdentityOverride
from gca_core.identity import resolve_developer


def _head(conn) -> uuid.UUID:  # type: ignore[no-untyped-def]
    repo = conn.execute(
        text(
            "INSERT INTO repository (id, github_id, full_name, installation_id, active) "
            "VALUES (gen_random_uuid(), (random()*1e9)::bigint, 'o/r', 1, true) RETURNING id"
        )
    ).scalar()
    change = conn.execute(
        text(
            "INSERT INTO change (id, repository_id, pr_number, opened_by_github_id, state) "
            "VALUES (gen_random_uuid(), :r, 1, 7, 'open') RETURNING id"
        ),
        {"r": repo},
    ).scalar()
    return conn.execute(
        text(
            "INSERT INTO change_head (id, change_id, head_sha, event_received_at, status, coverage_status, "
            "coverage_reasons, key_gens, counts, excluded_paths, is_final, attempts) "
            "VALUES (gen_random_uuid(), :c, "
            "'abc', now(), 'pending', 'pending', '{}', '{}', '{}', '[]', false, 0) RETURNING id"
        ),
        {"c": change},
    ).scalar()


@pytest.mark.parametrize(
    ("outcome", "tier", "conf", "dev", "gh", "ev", "ok"),
    [
        ("ai_unmodified", "exact", None, True, 7, True, True),
        ("ai_modified", "anchored", "high", True, 7, True, True),
        ("ai_modified", "broad", "lower", True, 7, True, True),
        ("human", "none", None, True, 7, False, True),
        ("not_observed", "none", None, False, None, False, True),
        ("ai_modified", "anchored", "lower", True, 7, True, False),  # confidence must match tier
        ("ai_unmodified", "exact", None, True, 7, False, False),  # AI requires a capture match
        ("not_observed", "none", None, True, 7, False, False),  # not_observed iff unmapped
        ("human", "none", None, True, None, False, False),  # null github id -> must be not_observed
        ("human", "exact", None, True, 7, False, False),  # exact iff ai_unmodified
    ],
)
def test_line_result_constraints(pg_engine: Engine, outcome, tier, conf, dev, gh, ev, ok) -> None:  # type: ignore[no-untyped-def]
    with pg_engine.connect() as conn:
        tx = conn.begin()
        try:
            head = _head(conn)
            dev_id = conn.execute(
                text(
                    "INSERT INTO developer (id, github_id, github_login, created_at) VALUES "
                    "(gen_random_uuid(), (random()*1e9)::bigint, 'x', now()) RETURNING id"
                )
            ).scalar()
            stmt = text(
                "INSERT INTO line_result (change_head_id, file_path, line_no, outcome, tier, confidence, "
                "credited_developer_id, credited_github_id, matched_capture_event_id) VALUES "
                "(:h, 'a.py', 1, :o, :t, :c, :d, :g, :e)"
            )
            params = {
                "h": head,
                "o": outcome,
                "t": tier,
                "c": conf,
                "d": dev_id if dev else None,
                "g": gh,
                "e": uuid.uuid4() if ev else None,
            }
            if ok:
                conn.execute(stmt, params)
            else:
                with pytest.raises(IntegrityError):
                    conn.execute(stmt, params)
        finally:
            tx.rollback()


def test_captured_line_partitions_and_checks(pg_engine: Engine) -> None:
    with pg_engine.connect() as conn:
        tx = conn.begin()
        try:
            row = {
                "t": datetime.now(UTC),
                "e": uuid.uuid4(),
                "d": uuid.uuid4(),
                "x": b"\x00" * 16,
                "m": [0] * 128,
            }
            conn.execute(
                text(
                    "INSERT INTO captured_line (captured_at, capture_event_id, developer_id, "
                    "tool_call_ordinal,"
                    " line_ordinal, path_suffix_fps, exact_fp, minhash, alg, key_gen) VALUES "
                    "(:t, :e, :d, 0, 1, '{}', :x, :m, 1, 1)"
                ),
                row,
            )
            part = conn.execute(text("SELECT tableoid::regclass::text FROM captured_line LIMIT 1")).scalar()
            assert part.startswith("captured_line_2")
            insert = text(
                "INSERT INTO captured_line (captured_at, capture_event_id, developer_id, "
                "tool_call_ordinal, line_ordinal, path_suffix_fps, exact_fp, minhash, alg, key_gen)"
                " VALUES (:t, :e, :d, 0, :l, '{}', :x, :m, 1, 1)"
            )
            for bad in (
                {"l": 2, "x": b"\x00" * 3},  # exact_fp is 16 bytes
                {"l": 3, "m": [0] * 32},  # a signature is 128 values
                {"l": 1},  # one row per (event, tool call, line): a redelivered part adds nothing
            ):
                nested = conn.begin_nested()
                with pytest.raises(IntegrityError):
                    conn.execute(insert, {**row, **bad})
                nested.rollback()
        finally:
            tx.rollback()


def test_one_active_key_generation(pg_engine: Engine) -> None:
    with pg_engine.connect() as conn:
        tx = conn.begin()
        try:
            with pytest.raises(IntegrityError):
                conn.execute(text("INSERT INTO key_generation (id, status) VALUES (2, 'active')"))
        finally:
            tx.rollback()


def test_resolve_developer_override_wins(pg_engine: Engine) -> None:
    with Session(pg_engine) as s:
        alice = Developer(github_id=1001, github_login="alice")
        admin = Developer(github_id=1002, github_login="admin")
        s.add_all([alice, admin])
        s.flush()
        s.add(
            IdentityOverride(
                github_id=5555, developer_id=alice.id, reason="service account", created_by=admin.id
            )
        )
        s.flush()
        assert resolve_developer(s, 1001).id == alice.id  # type: ignore[union-attr]
        assert resolve_developer(s, 5555).id == alice.id  # type: ignore[union-attr]
        assert resolve_developer(s, 9999) is None
        assert resolve_developer(s, None) is None
        s.rollback()
