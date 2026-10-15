"""Declarative base and shared column helpers. No table holds code or prompt text (Constitution II)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def pg_enum(cls: type[enum.Enum], name: str) -> SAEnum:
    """A native PostgreSQL enum storing the enum *values* (lower-case strings)."""
    return SAEnum(cls, name=name, values_callable=lambda e: [m.value for m in e], native_enum=True)


def uuid_pk():  # type: ignore[no-untyped-def]
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at():  # type: ignore[no-untyped-def]
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


Timestamp = datetime


# ------------------------------------------------------------------ minhash storage (data-model: int4[32])
_U32 = 1 << 32


def u32_to_i32(values: tuple[int, ...] | list[int]) -> list[int]:
    """MinHash values are uint32; PostgreSQL int4 is signed. Store as two's complement (lossless)."""
    return [v - _U32 if v >= (1 << 31) else v for v in values]


def i32_to_u32(values: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    return tuple(v + _U32 if v < 0 else v for v in values)
