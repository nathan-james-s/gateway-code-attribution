"""How fast one ingest replica stores captured lines (T114, T115; SC-013).

Stores capture events of about 40 real fingerprinted lines each through ``gca_ingest.store.handle``, one
transaction per message as the consumer does, into PostgreSQL 17 (the migrated schema), and reports lines per
second. NATS isn't involved: it only carries the messages. For docs/sizing.md, which compares this with the rate
an install has to sustain.

    uv run python -m tests.perf.ingest_rate --events 1000
"""

from __future__ import annotations

import argparse
import json
import random
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from gca_core import messages
from gca_ingest.store import handle
from gcattr import CapturedToolOutput, extract

from .prcheck_scale import KEY, code_line, database

HERE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--events", type=int, default=1000)
    ap.add_argument("--lines-per-event", type=int, default=40)
    ap.add_argument("--out", type=Path, default=HERE / "results" / "ingest_rate.json")
    args = ap.parse_args(argv)
    rng = random.Random(7)
    pg, url = database()
    try:
        engine = create_engine(url)
        with engine.begin() as conn:
            dev = conn.execute(
                text(
                    "INSERT INTO developer (id, github_id, github_login) VALUES (gen_random_uuid(), 77, 'perf') RETURNING id"
                )
            ).scalar()
            cred = conn.execute(
                text(
                    "INSERT INTO gateway_credential (id, developer_id, gateway_type, key_hash, status) "
                    "VALUES (gen_random_uuid(), :d, 'agentgateway', :h, 'active') RETURNING id"
                ),
                {"d": dev, "h": "sha256:" + "0" * 64},
            ).scalar()
            conn.execute(text("SELECT gca_ensure_partitions(1)"))
        iid = str(uuid.uuid4())
        msgs = []
        for n in range(args.events):
            content = "".join(code_line(rng) + "\n" for _ in range(args.lines_per_event))
            out = CapturedToolOutput(
                "anthropic_messages",
                "Write",
                "json_args",
                {"file_path": f"/w/src/f{n}.py", "content": content},
                True,
            )
            body = messages.event_body(
                api_format="anthropic_messages",
                model="m",
                received_at=datetime.now(UTC).isoformat(),
                status="captured",
                alg=1,
                key_gen=1,
                lines=extract(out, KEY, 1, 1),
                tool_call_count=1,
                credential_id=str(cred),
            )
            env = {"schema": messages.SCHEMA_ID, "instance_id": iid, "seq": n, "gateway_type": "agentgateway",
                   "sent_at": datetime.now(UTC).isoformat()}  # fmt: skip
            msgs.append(messages.decode(messages.encode({**env, **body})))
        lines = sum(len(m["lines"]) for m in msgs)
        t0 = time.monotonic()
        for m in msgs:
            with engine.begin() as conn:
                handle(conn, m)
        seconds = time.monotonic() - t0
        report = {
            "events": args.events,
            "lines": lines,
            "seconds": round(seconds, 1),
            "lines_per_second": round(lines / seconds),
            "events_per_second": round(args.events / seconds, 1),
        }
        print(json.dumps(report, indent=1))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=1) + "\n")
        return 0
    finally:
        pg.stop()


if __name__ == "__main__":
    raise SystemExit(main())
