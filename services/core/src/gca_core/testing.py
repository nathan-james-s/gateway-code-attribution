"""Shared pytest fixtures for service test suites: a migrated PostgreSQL 17 (testcontainers).

Import into a conftest:  ``from gca_core.testing import pg_engine, pg_url  # noqa: F401``
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

CORE = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    try:
        from testcontainers.community.postgres import PostgresContainer  # type: ignore[import-not-found]
    except ImportError:
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError:  # pragma: no cover
            pytest.skip("testcontainers not installed")
    try:
        container = PostgresContainer(
            "postgres:17",
            username="gca",
            password="gca",  # noqa: S106 - throwaway test container
            dbname="gca",
            driver="psycopg",
        )
        container.start()
    except Exception as exc:  # pragma: no cover - no Docker
        pytest.skip(f"Docker not available: {exc}")
    url = container.get_connection_url()
    env = {**os.environ, "GCA_DATABASE_URL": url}
    subprocess.run(
        ["alembic", "upgrade", "head"],  # noqa: S607 - alembic from the uv environment
        cwd=CORE,
        env=env,
        check=True,
        capture_output=True,
    )
    try:
        yield url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def pg_engine(pg_url: str) -> Engine:
    return create_engine(pg_url)
