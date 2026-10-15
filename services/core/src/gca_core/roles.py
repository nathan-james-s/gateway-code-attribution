"""Viewer roles and per-developer visibility (T083; FR-029, FR-029a; data-model.md "Working out a viewer's role").

1. GitHub defaults, checked live with the viewer's own GitHub token and cached for at most 60 seconds:
   organization owner -> admin; maintainer of team T -> team lead for T.
2. In-stack `ViewerRoleGrant` grants and revokes, read on every request, so they apply at the next page load.
3. Anyone else -> other.

Logins in `portal.adminLogins` are always admins: they are the break-glass entry, and the only admins an install on
a personal account has (it has no organization owners). A revoke doesn't remove them; the Helm value does.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, Collection, Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

__all__ = [
    "EFFECTIVE_MEMBERS_AT",
    "GITHUB_ROLE_TTL_SECONDS",
    "VISIBLE_ROLE_NAMES",
    "GithubRoleCache",
    "GithubRoles",
    "Roles",
    "can_view_developer",
    "can_view_team",
    "github_roles",
    "roles_for",
    "team_member_ids",
]

GITHUB_ROLE_TTL_SECONDS = 60.0
VISIBLE_ROLE_NAMES = ("admin", "team_lead", "other")

# Effective membership at :t (data-model.md TeamMembership): GitHub members + override adds - override removes.
EFFECTIVE_MEMBERS_AT = """
    SELECT m.team_id, m.developer_id
    FROM team_membership m
    WHERE m.valid_from <= :t AND (m.valid_to IS NULL OR :t < m.valid_to)
    GROUP BY m.team_id, m.developer_id
    HAVING bool_or(m.source = 'github' OR m.override_action = 'add')
       AND NOT bool_or(m.source = 'override' AND m.override_action = 'remove')
"""


@dataclass(frozen=True)
class GithubRoles:
    owner: bool = False
    maintains: frozenset[str] = frozenset()  # team slugs


@dataclass(frozen=True)
class Roles:
    admin: bool = False
    lead_of: frozenset[uuid.UUID] = frozenset()

    @property
    def names(self) -> list[str]:
        out = (["admin"] if self.admin else []) + (["team_lead"] if self.lead_of else [])
        return out or ["other"]


async def github_roles(user: Any, org: str, login: str) -> GithubRoles:
    """The viewer's current GitHub roles. Any GitHub error reads as "no role" (fail closed)."""
    if not org:
        return GithubRoles()
    owner = await user.org_role(org) == "admin"
    maintains = frozenset(s.lower() for s in await user.maintained_teams(org, login))
    return GithubRoles(owner, maintains)


@dataclass
class GithubRoleCache:
    """Per-login cache of GitHub-derived roles, so GitHub-side changes apply within `ttl` seconds (FR-029a)."""

    ttl: float = GITHUB_ROLE_TTL_SECONDS
    clock: Callable[[], float] = time.monotonic
    _data: dict[str, tuple[float, GithubRoles]] = field(default_factory=dict)

    async def get(self, login: str, fetch: Callable[[], Awaitable[GithubRoles]]) -> GithubRoles:
        key = login.lower()
        hit = self._data.get(key)
        if hit is not None and self.clock() - hit[0] < self.ttl:
            return hit[1]
        roles = await fetch()
        self._data[key] = (self.clock(), roles)
        return roles


def roles_for(
    conn: Connection,
    developer_id: uuid.UUID,
    login: str,
    github: GithubRoles,
    admin_logins: Iterable[str] = (),
) -> Roles:
    configured_admin = login.lower() in {a.lower() for a in admin_logins}
    admin = github.owner or configured_admin
    lead_of: set[uuid.UUID] = set()
    if github.maintains:
        lead_of = {
            r.id
            for r in conn.execute(
                text("SELECT id FROM team WHERE source = 'github' AND lower(slug) = ANY(:s)"),
                {"s": sorted(github.maintains)},
            )
        }
    grants = conn.execute(
        text(
            "SELECT role::text AS role, team_id, action::text AS action FROM viewer_role_grant "
            "WHERE developer_id = :d ORDER BY created_at, id"
        ),
        {"d": developer_id},
    )
    for g in grants:
        if g.role == "admin":
            admin = g.action == "grant" or configured_admin
        elif g.action == "grant":
            lead_of.add(g.team_id)
        else:
            lead_of.discard(g.team_id)
    return Roles(admin, frozenset(lead_of))


def _settings(conn: Connection) -> tuple[bool, set[str]]:
    row = conn.execute(
        text("SELECT per_developer_enabled, visible_roles FROM portal_settings WHERE id = 1")
    ).first()
    if row is None:
        return True, {"admin", "team_lead"}
    return bool(row.per_developer_enabled), set(row.visible_roles)


def team_member_ids(conn: Connection, team_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
    """Current effective members of the given teams."""
    if not team_ids:
        return set()
    rows = conn.execute(
        text(f"SELECT developer_id FROM ({EFFECTIVE_MEMBERS_AT}) e WHERE e.team_id = ANY(:teams)"),  # noqa: S608
        {"t": _now(conn), "teams": list(team_ids)},
    )
    return {r.developer_id for r in rows}


def _now(conn: Connection) -> Any:
    return conn.execute(text("SELECT now()")).scalar_one()


def can_view_developer(conn: Connection, roles: Roles, target_developer_id: uuid.UUID) -> bool:
    """FR-029 defaults: admins see every developer; team leads see members of the teams they lead; others none."""
    enabled, visible = _settings(conn)
    if not enabled:
        return False
    if "other" in visible or (roles.admin and "admin" in visible):
        return True
    return "team_lead" in visible and target_developer_id in team_member_ids(conn, roles.lead_of)


def can_view_team(conn: Connection, roles: Roles, team_id: uuid.UUID) -> bool:
    enabled, visible = _settings(conn)
    if not enabled:
        return False
    if "other" in visible or (roles.admin and "admin" in visible):
        return True
    return "team_lead" in visible and team_id in roles.lead_of
