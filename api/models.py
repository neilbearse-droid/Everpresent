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
    # §9: per-tenant monthly cap, enforced in the dispatch loop before each
    # provider call — never after.
    monthly_spend_cap_usd: float = Field(default=50.0)

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


class RunStatus(StrEnum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"
    # Governance gate closed (§8): recorded, never silently skipped.
    gated = "gated"
    # Stopped by the per-tenant monthly spend cap (§9).
    capped = "capped"


class RunMode(StrEnum):
    A = "A"  # API retrieval (§6.1)
    B = "B"  # web-interface scraping (§6.2, arrives M4)


class Run(SQLModel, table=True):
    __tablename__ = "runs"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    trigger: str = Field(default="manual")  # "schedule" arrives M5
    status: RunStatus = Field(default=RunStatus.pending, index=True)
    surface_set: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    mode_set: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    cost_usd: float = Field(default=0.0)
    counts: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON))
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ResultStatus(StrEnum):
    ok = "ok"
    error = "error"


class ResultVariant(StrEnum):
    # The client-facing answer (web search available to the surface).
    search = "search"
    # Classifier input only: same query/persona with search disabled — the
    # other half of the dual-query diff (§6.1). Excluded from scoring.
    nosearch = "nosearch"


class Result(SQLModel, table=True):
    __tablename__ = "results"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="runs.id", index=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    # Soft references: YAML re-import replaces config rows wholesale, so
    # results snapshot the query/persona by value and keep the ids only as
    # unconstrained integers (see DECISIONS.md M2).
    query_id: int | None = Field(default=None, index=True)
    persona_id: int | None = None
    query_text: str
    persona_name: str
    persona_segment: str = ""
    surface: SurfaceCode
    mode: RunMode = Field(default=RunMode.A)
    variant: ResultVariant = Field(default=ResultVariant.search, index=True)
    status: ResultStatus = Field(default=ResultStatus.ok)
    error: str | None = None
    # Raw payload envelope in object storage; Postgres stores derived data
    # only (§5.1).
    raw_uri: str = ""
    response_hash: str = ""
    latency_ms: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class Citation(SQLModel, table=True):
    __tablename__ = "citations"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    result_id: int = Field(foreign_key="results.id", index=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    url: str
    domain: str = Field(index=True)
    # Rule-based categorization arrives with M3 processing.
    source_category: str = ""


class Mention(SQLModel, table=True):
    __tablename__ = "mentions"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    result_id: int = Field(foreign_key="results.id", index=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    entity_type: str = Field(index=True)  # brand | competitor
    entity_name: str  # snapshot by value (config re-imports replace rows)
    competitor_id: int | None = None  # soft reference
    position: int
    rank: int
    sentiment: str = "neutral"
    context_snippet: str = ""
    detector_version: str = ""


class QueryClassification(SQLModel, table=True):
    """Latest web-search-likelihood classification per (tenant, query,
    surface); upserted on every processed run. google_aio_* columns join at
    M6."""

    __tablename__ = "classifications"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    query_id: int | None = Field(default=None, index=True)  # soft reference
    query_text: str
    surface: SurfaceCode
    web_search_likelihood: str
    signals: dict = Field(default_factory=dict, sa_column=Column(JSON))
    classifier_version: str = ""
    run_id: int | None = None  # run that produced the latest value
    updated_at: datetime = Field(default_factory=utcnow)


class VisibilityDaily(SQLModel, table=True):
    __tablename__ = "visibility_daily"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    date: str = Field(index=True)  # ISO yyyy-mm-dd (UTC day of the run)
    surface: SurfaceCode
    persona_segment: str = Field(default="", index=True)
    brand_score: float = 0.0
    # {competitor_name: score 0-100}
    competitor_scores: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    # mention_rate / citation_rate / result_count for drill-down
    extras: dict = Field(default_factory=dict, sa_column=Column(JSON))
    scorer_version: str = ""
    computed_at: datetime = Field(default_factory=utcnow)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int | None = Field(default=None, foreign_key="tenants.id", index=True)
    actor: str  # email of the acting user
    action: str
    at: datetime = Field(default_factory=utcnow)
