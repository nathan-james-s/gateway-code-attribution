"""Portal settings (env prefix GCA_PORTAL_ / GCA_)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class PortalConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GCA_PORTAL_", extra="ignore")

    public_url: str = "http://localhost:8080"
    github_client_id: str = ""
    github_client_secret: str = ""
    github_org: str = ""
    gateway_type: Literal["agentgateway", "litellm"] = "agentgateway"
    gateway_public_url: str = "http://localhost:4000"
    grafana_url: str = "http://localhost:3000"
    # agentgateway: base config (Helm-owned) and live config (portal-rendered) ConfigMaps
    namespace: str = "default"
    agentgateway_base_configmap: str = ""
    agentgateway_live_configmap: str = ""
    # litellm
    litellm_url: str = "http://localhost:4000"
    litellm_master_key: str = ""
    session_ttl_seconds: int = 8 * 3600
    # Admins besides the organization's owners (an install on a personal account has no owners).
    admin_logins: list[str] = []
    # The fingerprint key Secret the portal rotates (empty: rotation unavailable).
    fingerprint_secret: str = ""
    retention_days: int = 90


@lru_cache(maxsize=1)
def portal_config() -> PortalConfig:
    return PortalConfig()
