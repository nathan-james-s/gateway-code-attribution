"""ASGI app for uvicorn: builds the portal from environment settings."""

from __future__ import annotations

from gca_core.db import engine

from .app import create_app

app = create_app(engine())
