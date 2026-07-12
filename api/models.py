"""Operational schema, §5.1. Ships milestone by milestone: M0 added the
identity tables, M1 adds tenant configuration (brand, competitors, personas,
queries, surfaces, governance, audit). Measurement tables (runs, results,
mentions, citations) arrive with M2+."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class TenantStatus(StrEnum):
    active = "active"
    gated = "gated"
    archived = "archived"


class SurfaceCode(StrEnum):
    """Measured surfaces (§5.1). The catalog is fixed in code; enablement is
    per-tenant via TenantSurface."""

    openai_api = "openai_api"
    chatgpt_web = "chatgpt_web"
    perplexity_web = "perplexity_web"
    gemini_web = "gemini_web"
    google_aio = "google_aio"


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    name: str
    slug: str = Field(unique=True, index=True)
    status: TenantStatus = Field(default=TenantStatus.active)
    # Clerk organizations map one-to-one to tenants (§7.3). Linked from the
    # admin panel once the org exists in Clerk.
    clerk_org_id: str | None = Field(default=None, unique=True, index=True)

    # Governance (§8): runs for a gated tenant are recorded, never silently
    # skipped. approved_utility_models must be a subset of the §4 allowlist —
    # enforced at the API layer and by test_governance.
    ai_processing_approved: bool = Field(default=False)
    approved_surfaces: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    approved_utility_models: list[str] = Field(default_factory=list, sa_column=Column(JSON))

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


class BrandProfile(SQLModel, table=True):
    __tablename__ = "brand_profiles"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    brand_name: str
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    domains: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class Competitor(SQLModel, table=True):
    __tablename__ = "competitors"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    name: str
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    domains: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class Persona(SQLModel, table=True):
    __tablename__ = "personas"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    name: str
    prompt_text: str
    segment_tag: str = Field(default="", index=True)


class Query(SQLModel, table=True):
    __tablename__ = "queries"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    text: str
    corpus_tag: str = Field(default="core", index=True)
    active: bool = Field(default=True)


class TenantSurface(SQLModel, table=True):
    __tablename__ = "tenant_surfaces"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    code: SurfaceCode = Field(index=True)
    enabled: bool = Field(default=False)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int | None = Field(default=None, foreign_key="tenants.id", index=True)
    actor: str  # email of the acting user
    action: str
    at: datetime = Field(default_factory=utcnow)
