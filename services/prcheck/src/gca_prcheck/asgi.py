"""ASGI app for uvicorn: builds the PR check from environment settings."""

from __future__ import annotations

import logging

from gca_core.config import settings
from gca_core.db import engine
from gca_core.github import AppClient
from gca_core.keys import KeyRing

from .app import create_app
from .config import prcheck_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
_cfg = prcheck_config()
app = create_app(engine(), _cfg, AppClient(_cfg.app_id, _cfg.private_key), KeyRing(settings().keys_dir))
