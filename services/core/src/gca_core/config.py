"""Service configuration from environment variables (prefix ``GCA_``)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "settings"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GCA_", extra="ignore")

    database_url: str = "postgresql+psycopg://gca:gca@localhost:5432/gca"
    nats_url: str = "nats://localhost:4222"
    gateway_type: Literal["agentgateway", "litellm"] = "agentgateway"
    matching_window_days: int = Field(default=14, ge=1)
    retention_days: int = Field(default=90, ge=1)
    keys_dir: str = "/var/run/gca/keys"
    # Capture runtime
    heartbeat_seconds: float = Field(default=5.0, gt=0)
    publish_buffer_max: int = Field(default=10_000, ge=1)


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
