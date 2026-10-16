"""Capture entities (data-model.md "Capture"; T028). Fingerprints and metadata only."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Sequence,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, pg_enum, uuid_pk
from .models_identity import GatewayType


class InstanceStatus(enum.Enum):
    active = "active"
    stale = "stale"  # no heartbeat for more than 15 seconds
    closed = "closed"


class ApiFormat(enum.Enum):
    openai_chat = "openai_chat"
    openai_responses = "openai_responses"
    anthropic_messages = "anthropic_messages"
    gemini_native = "gemini_native"


class EventStatus(enum.Enum):
    captured = "captured"
    partial = "partial"
    failed = "failed"


class LossCause(enum.Enum):
    seq_gap = "seq_gap"
    heartbeat_missed = "heartbeat_missed"
    truncated = "truncated"
    unparsable = "unparsable"
    unexpected_format = "unexpected_format"
    buffer_overflow = "buffer_overflow"
    publish_failed = "publish_failed"
    unsupported_combination = "unsupported_combination"
    unknown_credential = "unknown_credential"


_GW = pg_enum(GatewayType, "gateway_type")
_FMT = pg_enum(ApiFormat, "api_format")
_CAUSE = pg_enum(LossCause, "loss_cause")


class CaptureInstance(Base):
    __tablename__ = "capture_instance"
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    gateway_type: Mapped[GatewayType] = mapped_column(_GW, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=-1)
    status: Mapped[InstanceStatus] = mapped_column(pg_enum(InstanceStatus, "instance_status"), nullable=False)


class CaptureEvent(Base):
    __tablename__ = "capture_event"
    __table_args__ = (
        # "instance_id, seq unique together; gaps in seq mean loss"
        UniqueConstraint("instance_id", "seq"),
        # "failure_cause required unless status = captured"
        CheckConstraint("status = 'captured' OR failure_cause IS NOT NULL", name="failure_cause_required"),
        Index("ix_capture_event_developer_received", "developer_id", "received_at"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    developer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("developer.id"))
    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("gateway_credential.id"))
    gateway_type: Mapped[GatewayType] = mapped_column(_GW, nullable=False)
    api_format: Mapped[ApiFormat] = mapped_column(_FMT, nullable=False)
    tool_hint: Mapped[str | None] = mapped_column(String(64))
    session_id: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[EventStatus] = mapped_column(pg_enum(EventStatus, "event_status"), nullable=False)
    failure_cause: Mapped[LossCause | None] = mapped_column(_CAUSE)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alg: Mapped[int] = mapped_column(Integer, nullable=False)
    key_gen: Mapped[int] = mapped_column(SmallInteger, nullable=False)


captured_line_id_seq = Sequence("captured_line_id_seq")


class CapturedLine(Base):
    """Partitioned by day on captured_at (RANGE); partitions are created by gca_ensure_partitions()."""

    __tablename__ = "captured_line"
    __table_args__ = (
        CheckConstraint("octet_length(exact_fp) = 16", name="exact_fp_16_bytes"),
        CheckConstraint("array_length(minhash, 1) = 128", name="minhash_128"),
        CheckConstraint("coalesce(array_length(path_suffix_fps, 1), 0) <= 3", name="at_most_3_path_fps"),
        Index("ix_captured_line_dev_exact", "developer_id", "exact_fp", "captured_at"),
        # one row per line of an event, so a redelivered part of an event sent in parts adds nothing
        Index(
            "uq_captured_line_event_line",
            "capture_event_id",
            "tool_call_ordinal",
            "line_ordinal",
            "captured_at",
            unique=True,
        ),
        {"postgresql_partition_by": "RANGE (captured_at)"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, captured_line_id_seq, primary_key=True, server_default=captured_line_id_seq.next_value()
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    capture_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    developer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tool_call_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    line_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    path_suffix_fps: Mapped[list[bytes]] = mapped_column(ARRAY(BYTEA), nullable=False, default=list)
    exact_fp: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    minhash: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False
    )  # uint32 stored as int4 (base.py)
    alg: Mapped[int] = mapped_column(Integer, nullable=False)
    key_gen: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class LshBand(Base):
    __tablename__ = "lsh_band"
    __table_args__ = (
        CheckConstraint("band BETWEEN 0 AND 7", name="band_0_7"),
        CheckConstraint("octet_length(band_hash) = 8", name="band_hash_8_bytes"),
        Index("ix_lsh_band_lookup", "developer_id", "band", "band_hash", "captured_at"),
        {"postgresql_partition_by": "RANGE (captured_at)"},
    )
    captured_line_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    band: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    developer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    band_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class CaptureLoss(Base):
    __tablename__ = "capture_loss"
    __table_args__ = (
        CheckConstraint("count >= 1", name="count_positive"),
        Index("ix_capture_loss_period", "period_start", "period_end"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    instance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    cause: Mapped[LossCause] = mapped_column(_CAUSE, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # "period_end is null while ongoing"
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    developer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("developer.id"))
    gateway_type: Mapped[GatewayType] = mapped_column(_GW, nullable=False)
    api_format: Mapped[ApiFormat | None] = mapped_column(_FMT)
    tool_hint: Mapped[str | None] = mapped_column(String(64))
    # Migration 0005: the missing span of a seq_gap, and the failure message a row came from (deduplication).
    seq_first: Mapped[int | None] = mapped_column(BigInteger)
    seq_last: Mapped[int | None] = mapped_column(BigInteger)
    source_seq: Mapped[int | None] = mapped_column(BigInteger)


__all__ = [
    "ApiFormat",
    "CaptureEvent",
    "CaptureInstance",
    "CaptureLoss",
    "CapturedLine",
    "EventStatus",
    "InstanceStatus",
    "LossCause",
    "LshBand",
]
