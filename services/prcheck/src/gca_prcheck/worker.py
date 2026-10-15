"""Attribute pending PR heads (T053; research R11, R12).

Line text comes from GitHub into memory, is fingerprinted by gcattr, and is dropped when the head is done. It is
never logged or stored (Constitution II). Every changed file is either attributed or listed in `excluded_paths`
with a reason; nothing is dropped silently (Constitution I).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

import gcattr
from gca_core.db.base import i32_to_u32
from gca_core.github import AppClient, ChangedFile
from gca_core.identity import resolve_developer
from gca_core.keys import KeyRing
from gca_core.watermark import current_watermark
from gcattr import ALG, AddedLine, Candidate, FingerprintKey, LineOutcome

from . import checkrun
from .config import PrcheckConfig
from .coverage import loss_reasons
from .diff import MAX_ADDED_LINES, MAX_BLOB_BYTES, added_from_blobs, added_from_patch
from .exclusions import Rules, load_rules

log = logging.getLogger("gca.prcheck.worker")

_CLAIM = text("""
    UPDATE change_head SET status = 'processing', attempts = attempts + 1
    WHERE id = (
        SELECT id FROM change_head
        WHERE status = 'pending'
          AND (event_received_at <= CAST(:wm AS timestamptz)
               OR event_received_at <= now() - make_interval(secs => :cap))
        ORDER BY event_received_at
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING id
""")
_HEAD = text("""
    SELECT h.id, h.head_sha, h.base_sha, h.event_received_at, h.check_run_id, h.attempts,
           c.pr_number, r.full_name, r.installation_id
    FROM change_head h JOIN change c ON c.id = h.change_id JOIN repository r ON r.id = c.repository_id
    WHERE h.id = :h
""")
_CANDIDATES = text("""
    SELECT cl.capture_event_id::text AS event, cl.exact_fp, cl.minhash, cl.path_suffix_fps,
           cl.tool_call_ordinal, cl.line_ordinal, cl.alg, cl.key_gen,
           coalesce((SELECT array_agg(b.band_hash ORDER BY b.band) FROM lsh_band b
                     WHERE b.captured_line_id = cl.id AND b.captured_at = cl.captured_at), '{}') AS bands
    FROM captured_line cl
    WHERE cl.developer_id = :dev AND cl.captured_at >= :since AND cl.captured_at <= :until
""")


@dataclass
class HeadResult:
    lines: list[AddedLine]
    outcomes: list[LineOutcome]
    developer_by_github: dict[int, uuid.UUID]
    excluded: list[dict[str, str]]
    coverage_status: str
    coverage_reasons: list[str]
    key_gens: list[int]
    merge_base_sha: str


# ---------------------------------------------------------------------------------------------- GitHub reads
async def _file_added_lines(
    gh: AppClient, inst: int, owner: str, repo: str, f: ChangedFile, merge_base: str, head: str
) -> tuple[list[tuple[int, str]], str | None]:
    """(added lines, exclusion reason or None)."""
    if f.status == "removed":
        return [], None
    if f.patch is not None:
        added = added_from_patch(f.patch)
    elif f.additions == 0 and f.status == "renamed":
        return [], None  # pure rename
    else:
        # The compare API omits patches for large files or diffs: rebuild the diff from both versions.
        new = await gh.blob_text(inst, owner, repo, f.filename, head)
        if new is None:
            return [], "binary" if f.additions == 0 else "too_large"
        if len(new.encode()) > MAX_BLOB_BYTES:
            return [], "too_large"
        old = None
        if f.status != "added":
            old = await gh.blob_text(inst, owner, repo, f.previous_filename or f.filename, merge_base)
            if old is None:
                return [], "too_large"
        added = added_from_blobs(old, new)
    if len(added) > MAX_ADDED_LINES:
        return [], "too_large"
    return added, None


async def collect_lines(
    gh: AppClient,
    inst: int,
    full_name: str,
    pr: int,
    base_sha: str,
    head_sha: str,
    rules: Rules | None = None,
) -> tuple[list[AddedLine], list[dict[str, str]], str, list[str]]:
    """Added lines credited per R11 (blame at head, commit in the PR), excluded paths, merge base, reasons."""
    owner, repo = full_name.split("/", 1)
    cmp = await gh.compare(inst, owner, repo, base_sha, head_sha)
    reasons: list[str] = []
    if len(cmp.files) >= 300:  # the compare API lists at most 300 files
        reasons.append("more than 300 changed files; only the first 300 were attributed")
    authors = {c.sha: c.author_github_id for c in await gh.pr_commits(inst, owner, repo, pr)}
    lines: list[AddedLine] = []
    excluded: list[dict[str, str]] = []
    for f in cmp.files:
        if rules is not None and f.status != "removed" and rules.match(f.filename):
            excluded.append({"path": f.filename, "reason": "rule"})  # never read (FR-021)
            continue
        added, reason = await _file_added_lines(gh, inst, owner, repo, f, cmp.merge_base_sha, head_sha)
        if reason:
            excluded.append({"path": f.filename, "reason": reason})
            continue
        if not added:
            continue
        by_line: dict[int, str] = {}
        for rng in await gh.blame(inst, owner, repo, head_sha, f.filename):
            for n in range(rng.start, rng.end + 1):
                by_line[n] = rng.commit_sha
        for line_no, body in added:
            # A blame commit outside the PR, or one GitHub links to no account, leaves the line unmapped:
            # it is reported as not observed rather than guessed (FR-015).
            sha = by_line.get(line_no)
            lines.append(AddedLine(f.filename, line_no, body, authors.get(sha) if sha else None))
    return lines, excluded, cmp.merge_base_sha, reasons


# ---------------------------------------------------------------------------------------------- matching
def load_candidates(
    conn: Connection, developer_id: uuid.UUID, since: datetime, until: datetime
) -> list[Candidate]:
    rows = conn.execute(_CANDIDATES, {"dev": developer_id, "since": since, "until": until}).fetchall()
    return [
        Candidate(
            r.event,
            bytes(r.exact_fp),
            i32_to_u32(r.minhash),
            tuple(bytes(p) for p in r.path_suffix_fps),
            r.tool_call_ordinal,
            r.line_ordinal,
            r.alg,
            r.key_gen,
            tuple(bytes(b) for b in r.bands),
        )
        for r in rows
    ]


def match_lines(
    engine: Engine, lines: Sequence[AddedLine], keys: Mapping[int, FingerprintKey], until: datetime
) -> tuple[list[LineOutcome], dict[int, uuid.UUID], list[int]]:
    with Session(engine) as s:
        window = (
            s.execute(text("SELECT matching_window_days FROM portal_settings WHERE id = 1")).scalar() or 14
        )
        developer_by_github: dict[int, uuid.UUID] = {}
        for gid in sorted({ln.credited_github_id for ln in lines if ln.credited_github_id is not None}):
            dev = resolve_developer(s, gid)
            if dev is not None:
                developer_by_github[gid] = dev.id
        since = until - timedelta(days=int(window))
        candidates = {
            gid: load_candidates(s.connection(), dev_id, since, until)
            for gid, dev_id in developer_by_github.items()
        }
    outcomes = gcattr.attribute(lines, candidates, keys, ALG)
    key_gens = sorted({c.key_gen for cs in candidates.values() for c in cs})
    return outcomes, developer_by_github, key_gens


# ---------------------------------------------------------------------------------------------- storing
def store_result(engine: Engine, head_id: uuid.UUID, alg: int, result: HeadResult) -> dict[str, Any]:
    summary = gcattr.summarize(result.outcomes)
    counts = {**summary["counts"], "excluded": len(result.excluded)}
    rows = [
        {
            "h": head_id,
            "path": ln.file_path,
            "no": ln.line_no,
            "outcome": o.outcome,
            "tier": o.tier,
            "conf": o.confidence,
            "sim": o.similarity,
            "dev": result.developer_by_github.get(ln.credited_github_id)
            if o.outcome != "not_observed"
            else None,
            "gid": ln.credited_github_id,
            "ev": o.matched_capture_event_id,
        }
        for ln, o in zip(result.lines, result.outcomes, strict=True)
    ]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM line_result WHERE change_head_id = :h"), {"h": head_id})  # reruns
        if rows:
            conn.execute(
                text("""
                    INSERT INTO line_result (change_head_id, file_path, line_no, outcome, tier, confidence,
                                             similarity, credited_developer_id, credited_github_id,
                                             matched_capture_event_id)
                    VALUES (:h, :path, :no, CAST(:outcome AS line_outcome), CAST(:tier AS match_tier),
                            CAST(:conf AS match_confidence), :sim, :dev, :gid, CAST(:ev AS uuid))
                """),
                rows,
            )
        conn.execute(
            text("""
                UPDATE change_head
                SET status = 'complete', completed_at = now(), counts = CAST(:counts AS jsonb),
                    excluded_paths = CAST(:excluded AS jsonb), coverage_status = CAST(:cov AS coverage_status),
                    coverage_reasons = :reasons, alg = :alg, key_gens = :gens, merge_base_sha = :mb
                WHERE id = :h
            """),
            {
                "h": head_id,
                "counts": json.dumps(counts),
                "excluded": json.dumps(result.excluded),
                "cov": result.coverage_status,
                "reasons": result.coverage_reasons,
                "alg": alg,
                "gens": result.key_gens,
                "mb": result.merge_base_sha,
            },
        )
    return summary


def coverage_for(
    lines: Sequence[AddedLine],
    outcomes: Sequence[LineOutcome],
    *,
    capped_minutes: float | None = None,
    losses: Sequence[str] = (),
) -> tuple[str, list[str]]:
    """(coverage_status, reasons).

    - not_observed: no commit author of the change is mapped (FR-015);
    - incomplete: capture hadn't caught up when the pending cap expired (FR-017, R12), or capture lost
      something in the matching window that could be a credited author's (``losses``, from coverage.py; T089);
    - complete otherwise. Lines from unmapped authors in a partly mapped PR are noted as a reason.
    """
    unmapped = sum(1 for o in outcomes if o.outcome == "not_observed")
    if lines and unmapped == len(outcomes):
        return "not_observed", ["no commit author in this change uses a gateway credential"]
    reasons = (
        [f"{unmapped} lines from commit authors without a gateway credential are not observed"]
        if unmapped
        else []
    )
    if capped_minutes is not None:
        reasons = [f"capture had not caught up after {capped_minutes:g} minutes", *reasons]
    if capped_minutes is not None or losses:
        return "incomplete", [*reasons, *losses]
    return "complete", reasons


# ---------------------------------------------------------------------------------------------- loop
async def process_head(
    engine: Engine, gh: AppClient, keys: KeyRing, cfg: PrcheckConfig, head_id: uuid.UUID
) -> None:
    with engine.connect() as conn:
        h = conn.execute(_HEAD, {"h": head_id}).one()
        wm = current_watermark(conn)
    # Claimed by the cap rather than the watermark: attribute now, but say coverage is incomplete.
    capped = cfg.pending_cap_minutes if wm is None or wm < h.event_received_at else None
    lines, excluded, merge_base, reasons = await collect_lines(
        gh, h.installation_id, h.full_name, h.pr_number, h.base_sha, h.head_sha, load_rules(engine)
    )
    keys.reload()
    outcomes, devs, key_gens = await asyncio.to_thread(
        match_lines, engine, lines, keys.all, h.event_received_at
    )
    with engine.connect() as conn:
        window = conn.execute(text("SELECT matching_window_days FROM portal_settings WHERE id = 1")).scalar()
        losses = loss_reasons(conn, set(devs.values()), h.event_received_at, int(window or 14))
    coverage, coverage_reasons = coverage_for(lines, outcomes, capped_minutes=capped, losses=losses)
    reasons = [*coverage_reasons, *reasons]
    result = HeadResult(lines, outcomes, devs, excluded, coverage, reasons, key_gens, merge_base)
    summary = store_result(engine, head_id, ALG, result)
    notes = checkrun.annotations(
        [(ln.file_path, ln.line_no, o.outcome, o.tier) for ln, o in zip(lines, outcomes, strict=True)]
    )
    del lines, result  # line text leaves memory with the head
    owner, repo = h.full_name.split("/", 1)
    run_id = h.check_run_id or await checkrun.start(gh, h.installation_id, owner, repo, h.head_sha)
    await checkrun.complete(
        gh,
        h.installation_id,
        owner,
        repo,
        run_id,
        title_text=checkrun.title(summary, coverage, cfg.headline_includes_broad),
        summary=checkrun.summary_markdown(
            summary,
            coverage_status=coverage,
            coverage_reasons=reasons,
            excluded=excluded,
            alg=ALG,
            library_version=gcattr.__version__,
            key_gens=key_gens,
            portal_link=f"{cfg.portal_url}/changes/{h.full_name}/{h.pr_number}",
            include_broad=cfg.headline_includes_broad,
        ),
        notes=notes,
    )
    if run_id != h.check_run_id:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE change_head SET check_run_id = :r WHERE id = :h"), {"r": run_id, "h": head_id}
            )


def claim_ready(engine: Engine, cap_minutes: float = 10.0) -> uuid.UUID | None:
    """The oldest pending head that capture has caught up with, or that has waited past the cap (FR-017)."""
    with engine.begin() as conn:
        wm = current_watermark(conn)  # None when no capture instance is active: only the cap releases heads
        return conn.execute(_CLAIM, {"wm": wm, "cap": cap_minutes * 60}).scalar()


def _fail(engine: Engine, head_id: uuid.UUID, max_attempts: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE change_head
                SET status = CASE WHEN attempts >= :max THEN 'error'::head_status ELSE 'pending'::head_status END
                WHERE id = :h
            """),
            {"h": head_id, "max": max_attempts},
        )


async def run(engine: Engine, gh: AppClient, keys: KeyRing, cfg: PrcheckConfig) -> None:
    while True:
        head_id = None
        try:
            head_id = claim_ready(engine, cfg.pending_cap_minutes)
            if head_id is None:
                await asyncio.sleep(cfg.work_seconds)
                continue
            await process_head(engine, gh, keys, cfg, head_id)
        except Exception:
            log.exception("attribution failed for head %s", head_id)  # never includes line text
            if head_id is not None:
                _fail(engine, head_id, cfg.max_attempts)
            await asyncio.sleep(cfg.work_seconds)
