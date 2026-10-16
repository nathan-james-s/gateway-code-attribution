"""US2 PR-check behaviour (T070-T073): pending cap, exclusions, unmapped authors, per-head and merge results."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from gca_core.github import BlameRange, ChangedFile, Comparison
from gca_core.keys import KeyRing
from gca_prcheck import checkrun, events, polling, worker
from gca_prcheck.config import PrcheckConfig
from gca_prcheck.exclusions import DEFAULT_RULES, Rules
from gcattr import AddedLine, LineOutcome

NO = LineOutcome("not_observed", "none", None, None, None)
HUMAN = LineOutcome("human", "none", None, None, None)


@pytest.mark.parametrize(
    ("path", "excluded"),
    [
        ("poetry.lock", True),
        ("web/package-lock.json", True),
        ("vendor/lib.go", True),
        ("a/vendor/b/c.go", True),
        ("web/node_modules/x/index.js", True),
        ("static/app.min.js", True),
        ("dist/bundle.js", True),
        ("src/dist.py", False),
        ("src/app.py", False),
        ("docs/vendor.md", False),
    ],
)
def test_default_exclusion_rules(path: str, excluded: bool) -> None:
    assert Rules(DEFAULT_RULES).match(path) is excluded


def test_coverage_rules() -> None:
    lines = [AddedLine("a.py", 1, "x = 1", 5), AddedLine("a.py", 2, "y = 2", None)]
    assert worker.coverage_for(lines, [NO, NO])[0] == "not_observed"
    status, reasons = worker.coverage_for(lines, [HUMAN, NO])
    assert status == "complete" and "1 lines from commit authors" in reasons[0]
    status, reasons = worker.coverage_for(lines, [HUMAN, HUMAN], capped_minutes=10)
    assert status == "incomplete" and reasons == ["capture had not caught up after 10 minutes"]
    assert worker.coverage_for([], [])[0] == "complete"


def test_not_observed_title_never_says_human() -> None:
    from gcattr import summarize

    t = checkrun.title(summarize([NO, NO, NO]), "not_observed", False)
    assert t.startswith("Not observed · 3 lines") and "human" not in t


def _setup(pg_engine: Engine, world: SimpleNamespace, *, capture: bool = True) -> tuple[object, str, int]:
    gid, other = 8_000_000 + uuid.uuid4().int % 1_000_000, 9_100_000 + uuid.uuid4().int % 1_000_000
    full_name = f"acme/us2-{gid}"
    gh = world.FakeGitHub(gid, full_name, gid, other)
    with pg_engine.begin() as conn:
        if capture:
            world.capture(conn, gid)
        conn.execute(text("UPDATE capture_instance SET status = 'stale' WHERE status = 'active'"))
    return gh, full_name, gid


def _head(pg_engine: Engine, head_id: uuid.UUID) -> object:
    with pg_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT status::text, coverage_status::text, coverage_reasons, excluded_paths, is_final "
                "FROM change_head WHERE id = :h"
            ),
            {"h": head_id},
        ).one()


async def test_pending_cap_attributes_with_incomplete_coverage(
    pg_engine: Engine, keyring: KeyRing, world: SimpleNamespace
) -> None:
    gh, _, _ = _setup(pg_engine, world)
    await polling.poll_once(pg_engine, gh)  # type: ignore[arg-type]
    assert worker.claim_ready(pg_engine, cap_minutes=10) is None  # no capture instance: still waiting
    head_id = worker.claim_ready(pg_engine, cap_minutes=0)  # cap expired
    assert head_id is not None
    cfg = PrcheckConfig(pending_cap_minutes=10)
    await worker.process_head(pg_engine, gh, keyring, cfg, head_id)  # type: ignore[arg-type]
    h = _head(pg_engine, head_id)
    assert h.status == "complete" and h.coverage_status == "incomplete"  # type: ignore[attr-defined]
    assert "capture had not caught up" in h.coverage_reasons[0]  # type: ignore[attr-defined]
    assert "coverage: incomplete" in gh.updates[0]["output"]["title"]  # type: ignore[attr-defined]


async def test_exclusion_rule_lists_file_without_reading_it(
    pg_engine: Engine, keyring: KeyRing, world: SimpleNamespace
) -> None:
    gh, _, _ = _setup(pg_engine, world)
    gh.extra_files = [ChangedFile("web/package-lock.json", "modified", 900, "@@ -1 +1 @@\n+x", None)]  # type: ignore[attr-defined]
    await polling.poll_once(pg_engine, gh)  # type: ignore[arg-type]
    with pg_engine.begin() as conn:
        world.heartbeat(conn)
    head_id = worker.claim_ready(pg_engine)
    await worker.process_head(pg_engine, gh, keyring, PrcheckConfig(), head_id)  # type: ignore[arg-type]
    h = _head(pg_engine, head_id)  # type: ignore[arg-type]
    assert {"path": "web/package-lock.json", "reason": "rule"} in h.excluded_paths  # type: ignore[attr-defined]
    with pg_engine.connect() as conn:
        assert not conn.execute(
            text("SELECT count(*) FROM line_result WHERE change_head_id = :h AND file_path LIKE 'web/%'"),
            {"h": head_id},
        ).scalar()
    assert "`web/package-lock.json` (rule)" in gh.updates[0]["output"]["summary"]  # type: ignore[attr-defined]


async def test_no_mapped_author_is_not_observed(
    pg_engine: Engine, keyring: KeyRing, world: SimpleNamespace
) -> None:
    gh, _, _ = _setup(pg_engine, world, capture=False)  # the author never got a gateway credential
    await polling.poll_once(pg_engine, gh)  # type: ignore[arg-type]
    with pg_engine.begin() as conn:
        world.heartbeat(conn)
    head_id = worker.claim_ready(pg_engine)
    await worker.process_head(pg_engine, gh, keyring, PrcheckConfig(), head_id)  # type: ignore[arg-type]
    assert _head(pg_engine, head_id).coverage_status == "not_observed"  # type: ignore[arg-type,attr-defined]
    assert gh.updates[0]["output"]["title"].startswith("Not observed")  # type: ignore[attr-defined]


async def test_new_push_keeps_old_head_and_merge_marks_final(
    pg_engine: Engine, keyring: KeyRing, world: SimpleNamespace
) -> None:
    gh, full_name, _ = _setup(pg_engine, world)
    await polling.poll_once(pg_engine, gh)  # type: ignore[arg-type]
    gh.pr = {**gh.pr, "head": {"sha": "2" * 40}}  # type: ignore[attr-defined]  # a new push
    assert await polling.poll_once(pg_engine, gh) == 1  # type: ignore[arg-type]
    gh.is_open, gh.merged = False, True  # type: ignore[attr-defined]
    await polling.poll_once(pg_engine, gh)  # type: ignore[arg-type]
    with pg_engine.connect() as conn:
        change = conn.execute(
            text(
                "SELECT c.id, c.state::text, c.final_head_id, c.merged_at FROM change c "
                "JOIN repository r ON r.id = c.repository_id WHERE r.full_name = :fn"
            ),
            {"fn": full_name},
        ).one()
        heads = conn.execute(
            text("SELECT head_sha, is_final, id FROM change_head WHERE change_id = :c ORDER BY head_sha"),
            {"c": change.id},
        ).fetchall()
    assert change.state == "merged" and change.merged_at is not None
    assert [(h.head_sha[0], h.is_final) for h in heads] == [("2", True), ("h", False)]  # both heads kept
    assert change.final_head_id == heads[0].id


async def test_closed_without_merge(pg_engine: Engine, world: SimpleNamespace) -> None:
    gh, full_name, _ = _setup(pg_engine, world)
    await polling.poll_once(pg_engine, gh)  # type: ignore[arg-type]
    gh.is_open = False  # type: ignore[attr-defined]
    await polling.poll_once(pg_engine, gh)  # type: ignore[arg-type]
    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT c.state::text, c.final_head_id FROM change c JOIN repository r ON r.id = c.repository_id "
                "WHERE r.full_name = :fn"
            ),
            {"fn": full_name},
        ).one()
    assert row == ("closed", None)


async def test_rerun_is_idempotent(pg_engine: Engine, keyring: KeyRing, world: SimpleNamespace) -> None:
    gh, full_name, _ = _setup(pg_engine, world)
    await polling.poll_once(pg_engine, gh)  # type: ignore[arg-type]
    with pg_engine.begin() as conn:
        world.heartbeat(conn)
    head_id = worker.claim_ready(pg_engine)
    await worker.process_head(pg_engine, gh, keyring, PrcheckConfig(), head_id)  # type: ignore[arg-type]

    def snapshot() -> list[tuple[object, ...]]:
        with pg_engine.connect() as conn:
            return [
                tuple(r)
                for r in conn.execute(
                    text(
                        "SELECT file_path, line_no, outcome::text, tier::text FROM line_result "
                        "WHERE change_head_id = :h ORDER BY 1, 2"
                    ),
                    {"h": head_id},
                ).fetchall()
            ]

    first = snapshot()
    assert events.rerun_head(pg_engine, full_name, "h" * 40) == head_id
    assert _head(pg_engine, head_id).status == "pending"  # type: ignore[arg-type,attr-defined]
    with pg_engine.begin() as conn:
        world.heartbeat(conn)
    assert worker.claim_ready(pg_engine) == head_id
    await worker.process_head(pg_engine, gh, keyring, PrcheckConfig(), head_id)  # type: ignore[arg-type]
    assert snapshot() == first and len(gh.created) == 2  # a new check run for the re-run, same results  # type: ignore[attr-defined]


# Quickstart §2 "two mapped authors" (FR-012): developer B's own AI output, and two lines each author typed
# from the other's AI output. Blame credits each line to the author of the commit that last touched it.
TWO_AUTHOR_CAPTURED = (
    "def discount(order):\n    return round(order.subtotal * order.customer.loyalty_rate, 2)\n"
)
TWO_AUTHOR_FILE = [
    ("def total(items):", "c1"),  # A's capture
    ("    return sum(item.price * item.quantity for item in items if item.active)", "c1"),  # A's capture
    ("def discount(order):", "c2"),  # B's capture
    ("    return round(order.subtotal * order.customer.loyalty_rate, 2)", "c2"),  # B's capture
    ("    return round(order.subtotal * order.customer.loyalty_rate, 2)", "c1"),  # B's capture, A's commit
    (
        "    return sum(item.price * item.quantity for item in items if item.active)",
        "c2",
    ),  # A's capture, B's commit
]


async def test_two_mapped_authors_each_credited_for_their_own_commits(
    pg_engine: Engine, keyring: KeyRing, world: SimpleNamespace
) -> None:
    a, b = 8_000_000 + uuid.uuid4().int % 1_000_000, 9_100_000 + uuid.uuid4().int % 1_000_000
    full_name = f"acme/two-authors-{a}"

    class TwoAuthorGitHub(world.FakeGitHub):  # type: ignore[name-defined,misc]
        async def compare(self, inst: int, owner: str, repo: str, base: str, head: str) -> Comparison:
            patch = f"@@ -0,0 +1,{len(TWO_AUTHOR_FILE)} @@\n" + "\n".join(
                "+" + ln for ln, _ in TWO_AUTHOR_FILE
            )
            return Comparison(
                "m" * 40,
                [ChangedFile("src/app.py", "added", len(TWO_AUTHOR_FILE), patch, None)],
                ["c1", "c2"],
            )

        async def blame(self, inst: int, owner: str, repo: str, oid: str, path: str) -> list[BlameRange]:
            return [BlameRange(n, n, sha) for n, (_, sha) in enumerate(TWO_AUTHOR_FILE, start=1)]

    gh = TwoAuthorGitHub(a, full_name, a, b)  # commit c1 is A's, c2 is B's
    with pg_engine.begin() as conn:
        dev_a = world.capture(conn, a, login="ada")
        dev_b = world.capture(conn, b, login="bob", content=TWO_AUTHOR_CAPTURED)
        conn.execute(text("UPDATE capture_instance SET status = 'stale' WHERE status = 'active'"))
    await polling.poll_once(pg_engine, gh)  # type: ignore[arg-type]
    with pg_engine.begin() as conn:
        world.heartbeat(conn)
    head_id = worker.claim_ready(pg_engine)
    await worker.process_head(pg_engine, gh, keyring, PrcheckConfig(), head_id)  # type: ignore[arg-type]

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT lr.line_no, lr.outcome::text, lr.tier::text, lr.credited_developer_id, lr.credited_github_id, "
                "ce.developer_id AS matched_developer_id "
                "FROM line_result lr LEFT JOIN capture_event ce ON ce.id = lr.matched_capture_event_id "
                "WHERE lr.change_head_id = :h ORDER BY lr.line_no"
            ),
            {"h": head_id},
        ).fetchall()
    assert [tuple(r) for r in rows] == [
        (1, "ai_unmodified", "exact", dev_a, a, dev_a),
        (2, "ai_unmodified", "exact", dev_a, a, dev_a),
        (3, "ai_unmodified", "exact", dev_b, b, dev_b),
        (4, "ai_unmodified", "exact", dev_b, b, dev_b),
        # The other developer's AI output, committed by someone whose own captures never produced it: credited to
        # the commit's author and matched only against that author's captures, so neither AI nor the other author.
        (5, "human", "none", dev_a, a, None),
        (6, "human", "none", dev_b, b, None),
    ]
    assert _head(pg_engine, head_id).coverage_status == "complete"  # type: ignore[arg-type,attr-defined]
