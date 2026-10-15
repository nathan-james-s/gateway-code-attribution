"""Database models and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from . import models_algorithm, models_attribution, models_capture, models_identity
from .base import Base

__all__ = [
    "Base",
    "engine",
    "models_algorithm",
    "models_attribution",
    "models_capture",
    "models_identity",
    "session",
]


@lru_cache(maxsize=1)
def engine() -> Engine:
    return create_engine(settings().database_url, pool_pre_ping=True)


@contextmanager
def session() -> Iterator[Session]:
    factory = sessionmaker(bind=engine(), expire_on_commit=False)
    with factory() as s:
        yield s
