"""The fingerprint key Secret (FR-035, FR-036): one file per key generation plus `active`.

The portal is the only writer: rotation adds a generation, and the key-sync loop removes expired ones. Key
material is generated here, written to the Secret and never logged, returned or stored in the database.
"""

from __future__ import annotations

import base64
import secrets
from typing import Any

__all__ = ["KeySecret"]


class KeySecret:
    def __init__(self, namespace: str, name: str, core_api: Any = None) -> None:
        self.namespace, self.name = namespace, name
        if core_api is None:
            from kubernetes import client, config

            config.load_incluster_config()
            core_api = client.CoreV1Api()
        self.api = core_api

    def generations(self) -> set[int]:
        data = self.api.read_namespaced_secret(self.name, self.namespace).data or {}
        return {int(k) for k in data if k.isdigit()}

    def add_generation(self, gen: int) -> None:
        """Write a new random 32-byte key for ``gen`` and make it the active generation."""
        if gen in self.generations():
            raise ValueError(f"key generation {gen} already exists")
        key = base64.b64encode(secrets.token_bytes(32)).decode()
        # Each file holds the base64 key (gca_core.keys); Secret data adds a second base64 layer.
        patch = {
            "data": {
                str(gen): base64.b64encode(key.encode()).decode(),
                "active": base64.b64encode(str(gen).encode()).decode(),
            }
        }
        self.api.patch_namespaced_secret(self.name, self.namespace, patch)

    def remove_generations(self, gens: set[int]) -> None:
        if not gens:
            return
        # A JSON merge patch with null deletes the key from the Secret's data.
        self.api.patch_namespaced_secret(self.name, self.namespace, {"data": {str(g): None for g in gens}})
