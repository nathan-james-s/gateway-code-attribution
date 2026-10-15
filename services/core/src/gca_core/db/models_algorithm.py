"""Algorithm versions and key generations (data-model.md "Algorithm and keys"; T027)."""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Numeric, SmallInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, pg_enum


class KeyStatus(enum.Enum):
    active = "active"
    retired = "retired"
    expired = "expired"


class AlgorithmVersion(Base):
    __tablename__ = "algorithm_version"
    alg: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    library_version: Mapped[str] = mapped_column(String(64), nullable=False)
    unicode_version: Mapped[str] = mapped_column(String(16), nullable=False)
    anchored_threshold: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    broad_threshold: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    minhash_size: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    lsh_bands: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    lsh_rows: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    common_lines_version: Mapped[str] = mapped_column(String(16), nullable=False)
    released_at: Mapped[datetime] = created_at()


class KeyGeneration(Base):
    """Key material lives in a Kubernetes Secret, never in the database."""

    __tablename__ = "key_generation"
    __table_args__ = (
        # "exactly one is active"
        Index(
            "uq_key_generation_one_active", "status", unique=True, postgresql_where=text("status = 'active'")
        ),
        CheckConstraint("status = 'active' OR retired_at IS NOT NULL", name="retired_when_not_active"),
    )
    # "id smallint PK; carried on every fingerprint"
    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    status: Mapped[KeyStatus] = mapped_column(pg_enum(KeyStatus, "key_status"), nullable=False)
    created_at: Mapped[datetime] = created_at()
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "expires_at = retired_at + retention_days"
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = ["AlgorithmVersion", "KeyGeneration", "KeyStatus"]
