"""Gateway credential backends (research R5; docs/validation/R5-key-reload.md).

agentgateway: the portal renders the LIVE config = Helm-owned base config + one apiKey entry per active
credential (`keyHash` + `metadata: {credential_id, github_id}`) into a ConfigMap that agentgateway hot-reloads
(~13 s, plus the kubelet's ConfigMap sync). LiteLLM: virtual keys through its key-management API (open source).
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import yaml

log = logging.getLogger("gca.portal.backends")


@dataclass(frozen=True)
class ActiveKey:
    credential_id: str
    github_id: int
    key_hash: str  # sha256:<hex>


class CredentialBackend(Protocol):
    def issue(self, credential_id: str, github_id: int, key: str, key_hash: str) -> str | None: ...
    def revoke(self, credential_id: str, gateway_ref: str | None) -> None: ...
    def sync(self, active: list[ActiveKey]) -> None: ...
    def ensure(self) -> None: ...


def render_agentgateway_config(base_yaml: str, active: list[ActiveKey]) -> str:
    cfg = yaml.safe_load(base_yaml)
    live = copy.deepcopy(cfg)
    keys = [
        {"keyHash": k.key_hash, "metadata": {"credential_id": k.credential_id, "github_id": k.github_id}}
        for k in sorted(active, key=lambda k: k.credential_id)
    ]
    live["llm"]["policies"]["apiKey"]["keys"] = keys
    return yaml.safe_dump(live, sort_keys=False)


class AgentgatewayBackend:
    """Re-renders the whole live ConfigMap on every change (idempotent; also at portal start-up)."""

    def __init__(
        self, namespace: str, base_configmap: str, live_configmap: str, core_api: Any = None
    ) -> None:
        self.namespace = namespace
        self.base = base_configmap
        self.live = live_configmap
        if core_api is None:
            from kubernetes import client, config

            config.load_incluster_config()
            core_api = client.CoreV1Api()
        self.api = core_api

    def issue(self, credential_id: str, github_id: int, key: str, key_hash: str) -> str | None:
        return f"configmap/{self.live}"  # the key itself takes effect on the next sync()

    def revoke(self, credential_id: str, gateway_ref: str | None) -> None:
        return None  # removed on the next sync()

    def ensure(self) -> None:
        """Create the live config with no keys if it doesn't exist yet, so the gateway can start before the
        database is migrated. Never overwrites an existing live config (that would drop issued keys)."""
        try:
            self.api.read_namespaced_config_map(self.live, self.namespace)
        except Exception as exc:
            if getattr(exc, "status", None) != 404:
                raise
            self.sync([])

    def sync(self, active: list[ActiveKey]) -> None:
        base = self.api.read_namespaced_config_map(self.base, self.namespace).data["config.yaml"]
        body = {
            "metadata": {
                "name": self.live,
                "labels": {
                    "app.kubernetes.io/part-of": "gateway-code-attribution",
                    "app.kubernetes.io/managed-by": "gca-portal",
                },
            },
            "data": {"config.yaml": render_agentgateway_config(base, active)},
        }
        try:
            self.api.replace_namespaced_config_map(self.live, self.namespace, body)
        except Exception as exc:  # create on first run
            if getattr(exc, "status", None) != 404:
                raise
            self.api.create_namespaced_config_map(self.namespace, body)


class LiteLLMBackend:
    def __init__(self, base_url: str, master_key: str, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(base_url=base_url, timeout=15)
        self.headers = {"Authorization": f"Bearer {master_key}"}

    def issue(self, credential_id: str, github_id: int, key: str, key_hash: str) -> str | None:
        resp = self.client.post(
            "/key/generate",
            headers=self.headers,
            json={
                "key": key,
                "key_alias": credential_id,
                "user_id": str(github_id),
                "metadata": {"credential_id": credential_id},
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data.get("token") or data.get("key_name") or credential_id)

    def revoke(self, credential_id: str, gateway_ref: str | None) -> None:
        resp = self.client.post("/key/delete", headers=self.headers, json={"key_aliases": [credential_id]})
        if resp.status_code >= 400 and gateway_ref:
            resp = self.client.post("/key/delete", headers=self.headers, json={"keys": [gateway_ref]})
        if resp.status_code == 404:
            return  # already gone
        resp.raise_for_status()

    def sync(self, active: list[ActiveKey]) -> None:
        return None  # LiteLLM stores keys itself

    def ensure(self) -> None:
        return None


def make_backend(cfg: Any) -> CredentialBackend:
    """The backend for the configured gateway (PortalConfig)."""
    if cfg.gateway_type == "agentgateway":
        return AgentgatewayBackend(
            cfg.namespace, cfg.agentgateway_base_configmap, cfg.agentgateway_live_configmap
        )
    return LiteLLMBackend(cfg.litellm_url, cfg.litellm_master_key)
