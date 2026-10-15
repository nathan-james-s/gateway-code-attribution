"""A migrated PostgreSQL for the integration tests that run without a cluster (tests marked e2e need one)."""

from __future__ import annotations

from gca_core.testing import pg_engine, pg_url  # noqa: F401
