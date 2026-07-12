"""Operational schema, §5.1. M0 ships only what the seeded superadmin needs;
the measurement tables (runs, results, mentions, ...) arrive with their
milestones so each lands alongside the code that writes it."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class TenantStatus(StrEnum):
    active = "active"
    gated = "gated"
    archived = "archived"


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    name: str
    slug: str = Field(unique=True, index=True)
    status: TenantStatus = Field(default=TenantStatus.gated)
    created_at: datetime = Field(default_factory=utcnow)


class User(SQLModel, table=True):
    __tablename__ = "users"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    # Linked on first authenticated request; the seed row starts with only an
    # email so the superadmin can be provisioned before Clerk sign-up.
    clerk_user_id: str | None = Field(default=None, unique=True, index=True)
    email: str = Field(unique=True, index=True)
    display_name: str | None = None
    # Superadmin is cross-tenant, so it lives on the user rather than on a
    # membership row (see DECISIONS.md).
    is_superadmin: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)


class MembershipRole(StrEnum):
    owner = "owner"
    member = "member"


class Membership(SQLModel, table=True):
    __tablename__ = "memberships"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    role: MembershipRole = Field(default=MembershipRole.member)
    created_at: datetime = Field(default_factory=utcnow)
