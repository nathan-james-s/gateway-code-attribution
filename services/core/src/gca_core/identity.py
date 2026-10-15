"""Resolve a GitHub account to a developer (data-model.md "Resolving a GitHub account to a developer")."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db.models_identity import Developer, IdentityOverride

__all__ = ["resolve_developer"]


def resolve_developer(session: Session, github_id: int | None) -> Developer | None:
    """An IdentityOverride wins if one exists; otherwise Developer.github_id; otherwise None (unmapped)."""
    if github_id is None:
        return None
    override = session.scalar(select(IdentityOverride).where(IdentityOverride.github_id == github_id))
    if override is not None:
        return session.get(Developer, override.developer_id)
    return session.scalar(select(Developer).where(Developer.github_id == github_id))
