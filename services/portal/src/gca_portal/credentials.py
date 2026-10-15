"""Personal gateway credentials (T049): issue, revoke, and the active-key list the gateway needs.

Shared by the portal's routes and the operator command (`admin_cli`). A key is shown once and never stored:
only `sha256:<hex>` is kept.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from gca_core.db.models_identity import CredentialStatus, Developer, GatewayCredential, GatewayType

from .backends import ActiveKey, CredentialBackend

__all__ = [
    "active_credential",
    "active_keys",
    "issue",
    "key_hash",
    "new_key",
    "revoke",
    "revoke_by_id",
    "sync",
]


def key_hash(key: str) -> str:
    return "sha256:" + hashlib.sha256(key.encode()).hexdigest()


def new_key() -> str:
    # LiteLLM rejects virtual keys that don't start with "sk-"; one format serves both gateways.
    return "sk-gca-" + secrets.token_urlsafe(32)


def active_credential(s: Session, developer_id: uuid.UUID) -> GatewayCredential | None:
    return s.scalar(
        select(GatewayCredential).where(
            GatewayCredential.developer_id == developer_id,
            GatewayCredential.status == CredentialStatus.active,
        )
    )


def revoke(s: Session, backend: CredentialBackend, gateway_type: str, cred: GatewayCredential) -> None:
    # A key issued while the install used the other gateway doesn't exist in this one: just mark it revoked.
    if cred.gateway_type.value == gateway_type:
        backend.revoke(str(cred.id), cred.gateway_ref)
    cred.status = CredentialStatus.revoked
    cred.revoked_at = datetime.now(UTC)


def issue(
    engine: Engine, backend: CredentialBackend, gateway_type: str, developer_id: uuid.UUID, github_id: int
) -> tuple[GatewayCredential, str]:
    """Issue a new key (revoking the developer's previous one) and return it with the key, shown once."""
    key = new_key()
    with Session(engine, expire_on_commit=False) as s, s.begin():
        old = active_credential(s, developer_id)
        if old is not None:
            revoke(s, backend, gateway_type, old)
            s.flush()
        cred = GatewayCredential(
            developer_id=developer_id,
            gateway_type=GatewayType(gateway_type),
            key_hash=key_hash(key),
            status=CredentialStatus.active,
        )
        s.add(cred)
        s.flush()
        cred.gateway_ref = backend.issue(str(cred.id), github_id, key, cred.key_hash)
    sync(engine, backend)
    return cred, key


def active_keys(engine: Engine) -> list[ActiveKey]:
    with Session(engine) as s:
        rows = s.execute(
            select(GatewayCredential.id, Developer.github_id, GatewayCredential.key_hash)
            .join(Developer, Developer.id == GatewayCredential.developer_id)
            .where(GatewayCredential.status == CredentialStatus.active)
        ).all()
    return [ActiveKey(str(r[0]), int(r[1]), r[2]) for r in rows]


def sync(engine: Engine, backend: CredentialBackend) -> None:
    backend.sync(active_keys(engine))


def revoke_by_id(
    engine: Engine, backend: CredentialBackend, gateway_type: str, credential_id: uuid.UUID
) -> bool:
    """Admin revoke (T075): the same gateway-side removal as a developer's own revoke. False if not active."""
    with Session(engine, expire_on_commit=False) as s, s.begin():
        cred = s.get(GatewayCredential, credential_id)
        if cred is None or cred.status != CredentialStatus.active:
            return False
        revoke(s, backend, gateway_type, cred)
    sync(engine, backend)
    return True
