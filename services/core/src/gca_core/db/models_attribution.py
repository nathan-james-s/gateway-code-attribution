"""Attribution entities (data-model.md "Attribution"; T029). No content columns."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, pg_enum, uuid_pk


class ChangeState(enum.Enum):
    open = "open"
    merged = "merged"
    closed = "closed"


class HeadStatus(enum.Enum):
    pending = "pending"
    processing = "processing"
    complete = "complete"
    error = "error"


class CoverageStatus(enum.Enum):
    complete = "complete"
    incomplete = "incomplete"
    pending = "pending"
    not_observed = "not_observed"


class LineOutcomeKind(enum.Enum):
    ai_unmodified = "ai_unmodified"
    ai_modified = "ai_modified"
    human = "human"
    indeterminate = "indeterminate"
    not_observed = "not_observed"  # a state for non-attributable lines, not an outcome (FR-009, FR-015)


class MatchTier(enum.Enum):
    exact = "exact"
    anchored = "anchored"
    broad = "broad"
    none = "none"


class MatchConfidence(enum.Enum):
    high = "high"
    lower = "lower"


class Repository(Base):
    __tablename__ = "repository"
    id: Mapped[uuid.UUID] = uuid_pk()
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(256), nullable=False)
    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    added_at: Mapped[datetime] = created_at()


class Change(Base):
    __tablename__ = "change"
    # "repository_id, pr_number unique together"
    __table_args__ = (UniqueConstraint("repository_id", "pr_number"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repository.id"), nullable=False)
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    opened_by_github_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[ChangeState] = mapped_column(pg_enum(ChangeState, "change_state"), nullable=False)
    final_head_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("change_head.id", use_alter=True, name="fk_change_final_head_id_change_head")
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChangeHead(Base):
    __tablename__ = "change_head"
    # "(change_id, head_sha) unique" -> idempotent reprocessing (FR-020)
    __table_args__ = (UniqueConstraint("change_id", "head_sha"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    change_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("change.id"), nullable=False, index=True)
    head_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    base_sha: Mapped[str | None] = mapped_column(String(64))
    merge_base_sha: Mapped[str | None] = mapped_column(String(64))
    event_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[HeadStatus] = mapped_column(pg_enum(HeadStatus, "head_status"), nullable=False)
    coverage_status: Mapped[CoverageStatus] = mapped_column(
        pg_enum(CoverageStatus, "coverage_status"), nullable=False
    )
    coverage_reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    alg: Mapped[int | None] = mapped_column(Integer)
    key_gens: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), nullable=False, default=list)
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # [{path, reason}] with reason enum rule | binary | too_large
    excluded_paths: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False, default=list)
    check_run_id: Mapped[int | None] = mapped_column(BigInteger)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LineResult(Base):
    __tablename__ = "line_result"
    __table_args__ = (
        CheckConstraint("(tier = 'exact') = (outcome = 'ai_unmodified')", name="exact_iff_unmodified"),
        CheckConstraint(
            "(tier IN ('anchored','broad')) = (outcome = 'ai_modified')", name="sim_iff_modified"
        ),
        CheckConstraint(
            "(tier = 'anchored' AND confidence = 'high') OR (tier = 'broad' AND confidence = 'lower') "
            "OR (tier IN ('exact','none') AND confidence IS NULL)",
            name="confidence_matches_tier",
        ),
        CheckConstraint(
            "(outcome = 'not_observed') = (credited_developer_id IS NULL)", name="not_observed_iff_unmapped"
        ),
        CheckConstraint(
            "credited_github_id IS NOT NULL OR outcome = 'not_observed'", name="null_github_unmapped"
        ),
        CheckConstraint(
            "outcome NOT IN ('ai_unmodified','ai_modified') OR matched_capture_event_id IS NOT NULL",
            name="ai_requires_match",
        ),
        CheckConstraint(
            "outcome <> 'indeterminate' OR matched_capture_event_id IS NULL", name="indeterminate_no_match"
        ),
    )
    change_head_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("change_head.id"), primary_key=True)
    file_path: Mapped[str] = mapped_column(Text, primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    outcome: Mapped[LineOutcomeKind] = mapped_column(pg_enum(LineOutcomeKind, "line_outcome"), nullable=False)
    tier: Mapped[MatchTier] = mapped_column(pg_enum(MatchTier, "match_tier"), nullable=False)
    confidence: Mapped[MatchConfidence | None] = mapped_column(pg_enum(MatchConfidence, "match_confidence"))
    similarity: Mapped[float | None] = mapped_column(Float)
    credited_developer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("developer.id"), index=True)
    credited_github_id: Mapped[int | None] = mapped_column(BigInteger)
    matched_capture_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


__all__ = [
    "Change",
    "ChangeHead",
    "ChangeState",
    "CoverageStatus",
    "HeadStatus",
    "LineOutcomeKind",
    "LineResult",
    "MatchConfidence",
    "MatchTier",
    "Repository",
]
