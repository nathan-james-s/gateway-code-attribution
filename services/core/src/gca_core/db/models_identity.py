"""Identity and access entities (data-model.md "Identity and access"; T026)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_at, pg_enum, uuid_pk


class GatewayType(enum.Enum):
    agentgateway = "agentgateway"
    litellm = "litellm"


class CredentialStatus(enum.Enum):
    active = "active"
    revoked = "revoked"


class TeamSource(enum.Enum):
    github = "github"
    manual = "manual"


class MembershipSource(enum.Enum):
    github = "github"
    override = "override"


class LeadSource(enum.Enum):
    github_maintainer = "github_maintainer"
    override = "override"


class OverrideAction(enum.Enum):
    add = "add"
    remove = "remove"


class Role(enum.Enum):
    admin = "admin"
    team_lead = "team_lead"


class GrantAction(enum.Enum):
    grant = "grant"
    revoke = "revoke"


class Developer(Base):
    __tablename__ = "developer"
    id: Mapped[uuid.UUID] = uuid_pk()
    # "github_id bigint unique, not null (the stable GitHub account ID; never the email)"
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    github_login: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at()
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GatewayCredential(Base):
    __tablename__ = "gateway_credential"
    __table_args__ = (
        # "key_hash sha256:<hex> of the key; the key itself is shown once at issue and never stored"
        CheckConstraint(r"key_hash ~ '^sha256:[0-9a-f]{64}$'", name="key_hash_format"),
        # "revoked_at is set only when status = revoked"
        CheckConstraint("(status = 'revoked') = (revoked_at IS NOT NULL)", name="revoked_at_iff_revoked"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    developer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer.id"), nullable=False, index=True)
    gateway_type: Mapped[GatewayType] = mapped_column(pg_enum(GatewayType, "gateway_type"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(71), nullable=False, unique=True)
    gateway_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CredentialStatus] = mapped_column(
        pg_enum(CredentialStatus, "credential_status"), nullable=False, default=CredentialStatus.active
    )
    issued_at: Mapped[datetime] = created_at()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdentityOverride(Base):
    __tablename__ = "identity_override"
    __table_args__ = (CheckConstraint("length(trim(reason)) > 0", name="reason_required"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    # "github_id unique; the account being mapped"
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    developer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # "created_by must hold the admin role" (enforced by the portal at write time)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer.id"), nullable=False)
    created_at: Mapped[datetime] = created_at()


class Team(Base):
    __tablename__ = "team"
    id: Mapped[uuid.UUID] = uuid_pk()
    # "github_team_id is unique when present; manual teams have none"
    github_team_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[TeamSource] = mapped_column(pg_enum(TeamSource, "team_source"), nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TeamMembership(Base):
    """Effective membership at T: rows with valid_from <= T < coalesce(valid_to, inf). Sync never deletes."""

    __tablename__ = "team_membership"
    __table_args__ = (CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="valid_period"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("team.id"), nullable=False, index=True)
    developer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer.id"), nullable=False, index=True)
    source: Mapped[MembershipSource] = mapped_column(
        pg_enum(MembershipSource, "membership_source"), nullable=False
    )
    override_action: Mapped[OverrideAction | None] = mapped_column(pg_enum(OverrideAction, "override_action"))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TeamLead(Base):
    __tablename__ = "team_lead"
    __table_args__ = (UniqueConstraint("team_id", "developer_id", "source"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("team.id"), nullable=False, index=True)
    developer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer.id"), nullable=False)
    source: Mapped[LeadSource] = mapped_column(pg_enum(LeadSource, "lead_source"), nullable=False)
    override_action: Mapped[OverrideAction | None] = mapped_column(pg_enum(OverrideAction, "override_action"))


class ViewerRoleGrant(Base):
    __tablename__ = "viewer_role_grant"
    # "team_lead requires team_id"
    __table_args__ = (
        CheckConstraint("role <> 'team_lead' OR team_id IS NOT NULL", name="team_lead_requires_team"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    developer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer.id"), nullable=False, index=True)
    role: Mapped[Role] = mapped_column(pg_enum(Role, "viewer_role"), nullable=False)
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("team.id"))
    action: Mapped[GrantAction] = mapped_column(pg_enum(GrantAction, "grant_action"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("developer.id"), nullable=False)
    created_at: Mapped[datetime] = created_at()


class PortalSettings(Base):
    __tablename__ = "portal_settings"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    per_developer_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    visible_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("ARRAY['admin','team_lead']")
    )
    matching_window_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("14"))
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("90"))
    exclusion_rules: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text(
            "ARRAY['**/*.lock','**/package-lock.json','**/vendor/**','**/node_modules/**','**/*.min.*','**/dist/**']"
        ),
    )


__all__ = [
    "CredentialStatus",
    "Developer",
    "GatewayCredential",
    "GatewayType",
    "GrantAction",
    "IdentityOverride",
    "LeadSource",
    "MembershipSource",
    "OverrideAction",
    "PortalSettings",
    "Role",
    "Team",
    "TeamLead",
    "TeamMembership",
    "TeamSource",
    "ViewerRoleGrant",
]

_ = UUID  # re-exported type used by sibling modules
