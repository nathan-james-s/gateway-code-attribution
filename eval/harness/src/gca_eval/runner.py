"""The evaluation runner (T106; FR-044; research R20).

For each gateway, with both gateways running locally (gca_eval.gateways) in front of an upstream that serves the
scenarios' recorded streams:

1. every scenario's streams are sent through the gateway with that scenario's developers' credentials, switching
   the fingerprint key generation where a scenario rotates it;
2. what capture publishes goes through ingest's real store (`gca_ingest.store.handle`) into a fresh PostgreSQL
   database (testcontainers), in publication order. NATS only transports those messages, so it isn't run; a
   `dropped` fault removes one message here, as a lost message would;
3. the scenario's repository is built with git, its pull request's added lines are read and credited by blame
   (`gcattr.gitlocal`, the same reading as the PR check; T097), and they're matched with the PR check's own
   `match_lines` against the stored captures.

The result keeps, per scenario, the lines, the candidates they were matched against and the keys, so calibration
(gca_eval.calibrate) can re-run matching under other thresholds without the gateways.
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from gca_core import messages as wire
from gca_ingest.store import handle
from gca_prcheck import worker
from gcattr import AddedLine, Candidate, FingerprintKey, LineOutcome
from gcattr.diff import DEFAULT_EXCLUSIONS, ExclusionRules
from gcattr.gitlocal import read_change

from . import gateways
from .gateways import GATEWAYS, Credential, replay, stack
from .scenario import Scenario, build_repo

__all__ = ["Case", "GatewayRun", "Run", "run"]

CORE = Path(__file__).resolve().parents[4] / "services" / "core"
KEYS = {1: b"\x31" * 32, 2: b"\x32" * 32}  # the eval's fingerprint keys, generations 1 and 2
MARK = "gca-eval stream="


@dataclass
class Case:
    """One scenario's pull request on one gateway."""

    scenario: str
    lines: list[AddedLine]
    outcomes: list[LineOutcome]
    candidates: dict[int, list[Candidate]]
    excluded: list[dict[str, str]]
    responses: int = 0
    captured: int = 0
    reported: dict[str, int] = field(default_factory=dict)  # loss cause -> count
    silent: int = 0
    client_errors: list[str] = field(default_factory=list)  # requests the gateway itself failed


@dataclass
class GatewayRun:
    gateway: str
    version: str
    cases: dict[str, Case] = field(default_factory=dict)


@dataclass
class Run:
    scenarios: list[Scenario]
    gateways: dict[str, GatewayRun]
    keys: dict[int, FingerprintKey]


def github_id(scenario: str, alias: str) -> int:
    """A fixed, scenario-scoped test account, so no scenario's captures can match another's lines."""
    return 7_000_000_000 + int(hashlib.sha256(f"{scenario}/{alias}".encode()).hexdigest()[:9], 16)


def credential(scenario: str, alias: str) -> Credential:
    cid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"gca-eval/{scenario}/{alias}"))
    return Credential(f"sk-gca-eval-{cid}", cid, github_id(scenario, alias))


# ---------------------------------------------------------------------------------------------- database
class Database:
    """A PostgreSQL container with one migrated database per gateway."""

    def __init__(self) -> None:
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("testcontainers[postgres] is needed to run the eval") from exc
        self.container = PostgresContainer(
            "postgres:17",
            username="gca",
            password="gca",  # noqa: S106 - a throwaway test container
            dbname="gca",
            driver="psycopg",
        )
        self.container.start()
        self.url = self.container.get_connection_url()

    def fresh(self, name: str) -> Engine:
        admin = create_engine(self.url, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        admin.dispose()
        url = self.url.rsplit("/", 1)[0] + f"/{name}"
        subprocess.run(
            ["alembic", "upgrade", "head"],  # noqa: S607
            cwd=CORE,
            env={**os.environ, "GCA_DATABASE_URL": url},
            check=True,
            capture_output=True,
        )
        return create_engine(url)

    def stop(self) -> None:
        self.container.stop()


def _developers(engine: Engine, gateway: str, scenarios: list[Scenario]) -> None:
    with engine.begin() as conn:
        for sc in scenarios:
            for alias in sc.authors:
                if alias == "base" or alias in sc.unmapped:
                    continue
                c = credential(sc.name, alias)
                dev = conn.execute(
                    text(
                        "INSERT INTO developer (id, github_id, github_login) VALUES (gen_random_uuid(), :g, :l) "
                        "RETURNING id"
                    ),
                    {"g": c.github_id, "l": f"{sc.name}-{alias}"[:64]},
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO gateway_credential (id, developer_id, gateway_type, key_hash, status) "
                        "VALUES (:id, :d, CAST(:gw AS gateway_type), :h, 'active')"
                    ),
                    {"id": c.credential_id, "d": dev, "gw": gateway,
                     "h": "sha256:" + hashlib.sha256(c.key.encode()).hexdigest()},
                )  # fmt: skip


# ---------------------------------------------------------------------------------------------- running
def _keys_dir(root: Path) -> Path:
    d = root / "keys"
    d.mkdir(parents=True)
    for gen, secret in KEYS.items():
        (d / str(gen)).write_text(base64.b64encode(secret).decode())
    (d / "active").write_text("1")
    return d


def _set_active(keys_dir: Path, gen: int) -> None:
    current = int((keys_dir / "active").read_text())
    if current != gen:
        (keys_dir / "active").write_text(str(gen))
        time.sleep(1.1)  # KeyRing reloads on a changed mtime; make sure the change is visible


def _responder(scenarios: list[Scenario]) -> Callable[[str, str, str], bytes | None]:
    by_key = {f"{sc.name}/{s.file}": sc.stream_bytes(s) for sc in scenarios for s in sc.streams}

    def respond(api_format: str, path: str, body: str) -> bytes | None:
        i = body.find(MARK)
        if i < 0:
            return None
        key = body[i + len(MARK) :].split('"', 1)[0].split("\\", 1)[0].split()[0]
        return by_key.get(key)

    return respond


def _attribute(engine: Engine, sc: Scenario, workdir: Path) -> tuple[list[AddedLine], list[dict[str, str]]]:
    repo = build_repo(sc, workdir)
    authors = {email: github_id(sc.name, alias) for alias, email in sc.authors.items()
               if alias != "base" and alias not in sc.unmapped}  # fmt: skip
    change = read_change(str(repo), sc.pr["base"], sc.pr["head"], rules=ExclusionRules(DEFAULT_EXCLUSIONS),
                         authors=authors)  # fmt: skip
    return change.lines, change.excluded


def _store(engine: Engine, msgs: list[dict[str, Any]]) -> None:
    with engine.begin() as conn:
        for m in msgs:
            handle(conn, wire.validate(m))


def _loss_counts(engine: Engine, since: datetime) -> dict[str, int]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT cause::text, sum(count) FROM capture_loss WHERE period_end >= :t GROUP BY 1"),
            {"t": since},
        ).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def run_gateway(
    gateway: str,
    stk: Any,
    engine: Engine,
    scenarios: list[Scenario],
    keys_dir: Path,
    keys: dict[int, FingerprintKey],
    workroot: Path,
    log: Callable[[str], None],
) -> GatewayRun:
    out = GatewayRun(gateway, stk.versions[gateway])
    _developers(engine, gateway, scenarios)
    stored = 0
    for sc in scenarios:
        case_started = datetime.now(UTC) - timedelta(seconds=1)
        responses = captured = silent = 0
        client_errors: list[str] = []
        dropped: set[tuple[str, int]] = set()
        for spec in sc.streams:
            _set_active(keys_dir, spec.key_gen)
            cred = credential(sc.name, spec.author)
            errors_before = len(gateways.client_errors)
            msgs = replay(stk.send(gateway, cred), lambda: stk.messages(gateway), spec.api_format,
                          f"{MARK}{sc.name}/{spec.file}")  # fmt: skip
            responses += 1
            failed_request = [f"{spec.file}: {e}" for e in gateways.client_errors[errors_before:]]
            client_errors += failed_request
            events = [m for m in msgs if m["kind"] == "event"]
            if spec.fault == "dropped" and events:
                dropped.add((events[0]["instance_id"], events[0]["seq"]))
                continue  # its event never reaches ingest; the next message reveals the sequence gap
            if events:
                captured += 1
            elif not any(m["kind"] == "failure" for m in msgs):
                silent += 1
        _set_active(keys_dir, 1)
        everything = stk.messages(gateway)
        new = [m for m in everything[stored:] if (m["instance_id"], m["seq"]) not in dropped]
        stored = len(everything)
        _store(engine, new)
        lines, excluded = _attribute(engine, sc, workroot / gateway / sc.name)
        until = datetime.now(UTC) + timedelta(seconds=1)
        outcomes, devs, _ = worker.match_lines(engine, lines, keys, until)
        candidates: dict[int, list[Candidate]] = {}
        with engine.connect() as conn:
            for gid, dev_id in devs.items():
                candidates[gid] = worker.load_candidates(conn, dev_id, until - timedelta(days=14), until)
        reported = _loss_counts(engine, case_started)
        # A dropped message is silent loss unless ingest reported the sequence gap it left.
        silent += max(0, len(dropped) - reported.get("seq_gap", 0))
        out.cases[sc.name] = Case(
            sc.name,
            lines,
            outcomes,
            candidates,
            excluded,
            responses,
            captured,
            reported,
            silent,
            client_errors,
        )
        log(
            f"  {gateway:12} {sc.name:32} {len(lines):3} lines, {responses} responses, loss {reported or '-'}"
        )
    return out


def run(
    scenarios: list[Scenario],
    gateways: tuple[str, ...] = GATEWAYS,
    log: Callable[[str], None] = print,
) -> Run:
    work = Path(tempfile.mkdtemp(prefix="gca-eval-"))
    keys = {g: FingerprintKey(g, s) for g, s in KEYS.items()}
    keys_dir = _keys_dir(work)
    creds = [
        credential(sc.name, a) for sc in scenarios for a in sc.authors if a != "base" and a not in sc.unmapped
    ]
    db = Database()
    try:
        with stack(keys_dir, creds, _responder(scenarios), gateways) as stk:
            runs = {}
            for gw in gateways:
                log(f"{gw}:")
                runs[gw] = run_gateway(gw, stk, db.fresh(f"eval_{gw}"), scenarios, keys_dir, keys, work, log)
        return Run(scenarios, runs, keys)
    finally:
        db.stop()
        shutil.rmtree(work, ignore_errors=True)
