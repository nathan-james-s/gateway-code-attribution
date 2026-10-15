"""PR check settings (env prefix GCA_PRCHECK_). App credentials come from the `github.existingSecret` Secret."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PrcheckConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GCA_PRCHECK_", extra="ignore")

    app_id: int = 0
    private_key: str = ""
    delivery: Literal["polling", "webhook"] = "polling"
    poll_seconds: float = Field(default=30.0, gt=0)
    work_seconds: float = Field(default=2.0, gt=0)
    portal_url: str = "http://localhost:8080"
    headline_includes_broad: bool = False
    max_attempts: int = Field(default=3, ge=1)
    pending_cap_minutes: float = Field(
        default=10.0, gt=0
    )  # R12: after this, attribute with incomplete coverage
    webhook_secret: str = ""
    # Team sync (T082) runs only for an organization install; a personal account has no teams.
    github_org: str = ""


@lru_cache(maxsize=1)
def prcheck_config() -> PrcheckConfig:
    return PrcheckConfig()
