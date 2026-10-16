"""The PR check at scale (T114; SC-009, SC-013) and storage per captured line (T115).

Fills PostgreSQL 17 (the migrated schema) with captures, then times the PR check's matching for a PR of 1,000
added lines:

- the PR author: every line they captured over the retention period (``--lines-per-day`` x ``--days``), with real
  fingerprints of synthetic code, in capture events of about 40 lines;
- the other developers (``--developers`` - 1): filler rows with random fingerprints, a ``--scale`` fraction of their
  full volume (indexes and tables grow as with real rows; their content can't match anyone);
- the PR: 60% exact copies of the author's lines from the matching window, 20% of them edited (one identifier
  renamed), 20% new lines.

What's timed is ``gca_prcheck.worker.match_lines``: resolving the credited developer, the indexed candidate
lookup and attribution. GitHub's API calls (diff, blame, check run) come on top and depend on GitHub, not on the
store. Also reports the measured bytes per captured line, for docs/sizing.md.

    uv run python -m tests.perf.prcheck_scale --scale 0.05
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from gca_core.db.base import bands_to_i64, u32_to_i32
from gca_prcheck.worker import lookup_candidates, match_lines
from gcattr import ALG, AddedLine, FingerprintKey, lookup_keys
from gcattr.fingerprint import exact_fp, path_suffix_fps
from gcattr.lexer import tokenize
from gcattr.normalize import normalize_line
from gcattr.similarity import lsh_bands, minhash
from gcattr.trivial import is_trivial

HERE = Path(__file__).resolve().parent
CORE = HERE.parents[1] / "services" / "core"
KEY = FingerprintKey(1, b"\x42" * 32)
AUTHOR_GITHUB_ID = 4242

WORDS = [
    "order",
    "item",
    "price",
    "total",
    "discount",
    "tax",
    "region",
    "customer",
    "invoice",
    "cart",
    "stock",
    "sku",
    "quantity",
    "amount",
    "user",
    "account",
    "session",
    "token",
    "config",
    "plugin",
    "report",
    "month",
    "period",
    "sale",
    "ledger",
    "entry",
    "payment",
    "refund",
    "shipment",
    "address",
    "email",
    "name",
    "status",
    "result",
    "value",
    "cache",
    "key",
    "queue",
    "job",
    "batch",
    "record",
    "event",
    "metric",
    "count",
    "limit",
    "offset",
    "page",
    "filter",
]


def code_line(rng: random.Random) -> str:
    """A synthetic, non-trivial line of Python-ish code."""
    a, b, c, d = (rng.choice(WORDS) for _ in range(4))
    n = rng.randint(2, 500)
    return rng.choice(
        [
            f"{a}_{b} = compute_{c}({a}.{d}, {b}={c}_{d}, limit={n})",
            f"if {a}.{b}_{c} > {n} and not {d}.is_{c}:",
            f"return [{a} for {a} in {b}_{c}s if {a}.{d} >= {n}]",
            f"{a}_{b}s.append(build_{c}({d}, {a}.{b}, retries={n}))",
            f'raise ValueError(f"invalid {a} {b}: {{{c}_{d}!r}} (max {n})")',
            f"total_{a} += {b}.{c} * {d}_rate / {n}",
            f'logger.info("{a} %s {b} %d", {c}.{d}, len({a}_{b}s))',
            f"{a} = {b}_repo.get_{c}({d}_id, include_{a}=True)",
        ]
    )


def fingerprint_row(line: str, path: str) -> tuple[bytes, list[int], list[int], list[bytes]] | None:
    tokens = tokenize(normalize_line(line, ALG))
    if is_trivial(tokens, ALG):
        return None
    sig = minhash(tokens, KEY, ALG)
    return (
        exact_fp(tokens, KEY, ALG),
        u32_to_i32(sig),
        bands_to_i64(lsh_bands(sig, KEY, ALG)),
        list(path_suffix_fps(path, KEY, ALG)),
    )


def database() -> tuple[Any, str]:
    try:
        from testcontainers.community.postgres import PostgresContainer  # type: ignore[import-not-found]
    except ImportError:
        from testcontainers.postgres import PostgresContainer

    pg = PostgresContainer("postgres:17", driver="psycopg")
    pg.start()
    url = pg.get_connection_url()
    subprocess.run(
        ["alembic", "upgrade", "head"], cwd=CORE, env={**os.environ, "GCA_DATABASE_URL": url}, check=True
    )
    return pg, url


def partitions(conn: Any, days: int) -> None:
    conn.execute(
        text(
            """
            DO $$
            DECLARE d date;
            BEGIN
                FOR d IN SELECT generate_series((now() AT TIME ZONE 'UTC')::date - :days,
                                                (now() AT TIME ZONE 'UTC')::date + 1, interval '1 day')::date LOOP
                    EXECUTE format('CREATE TABLE IF NOT EXISTS %I PARTITION OF captured_line FOR VALUES FROM (%L) TO (%L)',
                                   'captured_line_' || to_char(d, 'YYYYMMDD'), (d::timestamp AT TIME ZONE 'UTC'),
                                   ((d + 1)::timestamp AT TIME ZONE 'UTC'));
                END LOOP;
            END $$;
            """.replace(":days", str(int(days)))
        )
    )


def load_author(
    url: str, dev: uuid.UUID, args: argparse.Namespace, rng: random.Random
) -> dict[int, list[str]]:
    """The author's captures; returns their lines by days ago, to build the PR from."""
    import psycopg

    by_day: dict[int, list[str]] = {}
    now = datetime.now(UTC)
    cols = (
        "captured_at, capture_event_id, developer_id, tool_call_ordinal, line_ordinal, path_suffix_fps, exact_fp,"
        " minhash, bands, alg, key_gen"
    )
    with psycopg.connect(url.replace("postgresql+psycopg", "postgresql")) as conn, conn.cursor() as cur:
        with cur.copy(f"COPY captured_line ({cols}) FROM STDIN") as cp:
            cp.set_types(["timestamptz", "uuid", "uuid", "int4", "int4", "bytea[]", "bytea", "int4[]", "int8[]",
                          "int4", "int2"])  # fmt: skip
            for day in range(args.days):
                lines = by_day.setdefault(day, [])
                written = 0
                while written < args.lines_per_day:
                    event, at = uuid.uuid4(), now - timedelta(days=day, seconds=rng.randint(60, 86_000))
                    path = f"/work/src/{rng.choice(WORDS)}_{rng.choice(WORDS)}.py"
                    for ordinal in range(1, 41):
                        line = code_line(rng)
                        fp = fingerprint_row(line, path)
                        if fp is None:
                            continue
                        cp.write_row(
                            (at, event, dev, 1, ordinal, fp[3], fp[0], fp[1], fp[2], ALG, KEY.key_gen)
                        )
                        lines.append(line)
                        written += 1
        conn.commit()
    return by_day


def load_filler(conn: Any, developers: int, rows_per_day: int, days: int) -> None:
    """Other developers' captures: random fingerprints, same row shape and indexes."""
    for day in range(days):
        conn.execute(
            text(
                """
                INSERT INTO captured_line (captured_at, capture_event_id, developer_id, tool_call_ordinal,
                                           line_ordinal, path_suffix_fps, exact_fp, minhash, bands, alg, key_gen)
                SELECT now() - make_interval(days => :day, secs => (random() * 86000)::int),
                       md5(:day || '-' || (g / 40))::uuid, md5('dev-' || (g % :devs))::uuid, 1, g % 40 + 1,
                       ARRAY[decode(md5(g || 'p1'), 'hex'), decode(md5(g || 'p2'), 'hex')],
                       decode(md5(:day || '-' || g), 'hex'),
                       array_fill((random() * 2e9)::int - 1000000000, ARRAY[128]),
                       ARRAY[(random() * 9e18)::bigint, (random() * 9e18)::bigint, (random() * 9e18)::bigint,
                             (random() * 9e18)::bigint, (random() * 9e18)::bigint, (random() * 9e18)::bigint,
                             (random() * 9e18)::bigint, (random() * 9e18)::bigint],
                       1, 1
                FROM generate_series(1, :rows) g
                """
            ),
            {"day": day, "devs": max(developers, 1), "rows": rows_per_day},
        )


def pr_lines(by_day: dict[int, list[str]], window: int, n: int, rng: random.Random) -> list[AddedLine]:
    recent = [ln for d in range(window) for ln in by_day.get(d, [])]
    picked = rng.sample(recent, int(n * 0.8))
    out: list[str] = []
    for i, ln in enumerate(picked):
        if i < int(n * 0.6):
            out.append(ln)
        else:  # rename one identifier
            w = next((w for w in WORDS if w in ln), WORDS[0])
            out.append(ln.replace(w, w + "_v2", 1))
    out += [code_line(rng) + "  # new" for _ in range(n - len(out))]
    rng.shuffle(out)
    return [AddedLine(f"src/file_{i // 100}.py", i % 100 + 1, t, AUTHOR_GITHUB_ID) for i, t in enumerate(out)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--developers", type=int, default=500)
    ap.add_argument(
        "--lines-per-day", type=int, default=2000, help="captured non-trivial lines per developer"
    )
    ap.add_argument("--days", type=int, default=90, help="retention (days of captures kept)")
    ap.add_argument(
        "--scale", type=float, default=0.05, help="fraction of the other developers' volume to load"
    )
    ap.add_argument("--pr-lines", type=int, default=1000)
    ap.add_argument("--budget", type=float, default=120.0, help="SC-009: seconds")
    ap.add_argument("--out", type=Path, default=HERE / "results" / "prcheck_scale.json")
    args = ap.parse_args(argv)
    rng = random.Random(20261015)
    pg, url = database()
    try:
        engine = create_engine(url)
        dev = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO developer (id, github_id, github_login) VALUES (:d, :g, 'perf-author')"),
                {"d": dev, "g": AUTHOR_GITHUB_ID},
            )
            partitions(conn, args.days)
        t0 = time.monotonic()
        by_day = load_author(url, dev, args, rng)
        t_author = time.monotonic() - t0
        filler_per_day = int((args.developers - 1) * args.lines_per_day * args.scale)
        t0 = time.monotonic()
        with engine.begin() as conn:
            load_filler(conn, args.developers - 1, filler_per_day, args.days)
        t_filler = time.monotonic() - t0
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM ANALYZE captured_line"))
            rows = conn.execute(text("SELECT count(*) FROM captured_line")).scalar()
            size = int(
                conn.execute(
                    text(
                        "SELECT sum(pg_total_relation_size(c.oid)) FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
                        " WHERE i.inhparent = 'captured_line'::regclass"
                    )
                ).scalar()
            )
            window = conn.execute(
                text("SELECT matching_window_days FROM portal_settings WHERE id = 1")
            ).scalar()
        lines = pr_lines(by_day, int(window), args.pr_lines, rng)
        until = datetime.now(UTC)
        t0 = time.monotonic()
        with engine.connect() as conn:
            fetched = lookup_candidates(
                conn,
                dev,
                until - timedelta(days=int(window)),
                until,
                lookup_keys(lines, {1: KEY})[AUTHOR_GITHUB_ID],
            )
        t_lookup = time.monotonic() - t0
        t0 = time.monotonic()
        outcomes, _, _ = match_lines(engine, lines, {1: KEY}, until)
        t_match = time.monotonic() - t0
        counts: dict[str, int] = {}
        for o in outcomes:
            counts[o.outcome] = counts.get(o.outcome, 0) + 1
        report = {
            "settings": {k: v for k, v in vars(args).items() if k != "out"},
            "captured_lines": rows,
            "author_lines": sum(len(v) for v in by_day.values()),
            "captured_line_bytes": size,
            "bytes_per_line": round(size / rows),
            "matching_window_days": window,
            "candidates_fetched": len(fetched),
            "lookup_seconds": round(t_lookup, 2),
            "match_seconds": round(t_match, 2),
            "outcomes": counts,
            "load_seconds": {"author": round(t_author), "filler": round(t_filler)},
            "passed": t_match <= args.budget,
        }
        print(json.dumps(report, indent=1))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1) + "\n")
        return 0 if report["passed"] else 1
    finally:
        pg.stop()


if __name__ == "__main__":
    raise SystemExit(main())
