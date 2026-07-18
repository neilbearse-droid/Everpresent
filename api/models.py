"""Operational schema, §5.1. Ships milestone by milestone: M0 added the
identity tables, M1 adds tenant configuration (brand, competitors, personas,
queries, surfaces, governance, audit). Measurement tables (runs, results,
mentions, citations) arrive with M2+."""

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, Column, Index
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
    perplexity_api = "perplexity_api"
    claude_api = "claude_api"
    gemini_api = "gemini_api"
    chatgpt_web = "chatgpt_web"
    perplexity_web = "perplexity_web"
    gemini_web = "gemini_web"
    copilot_web = "copilot_web"
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
    # Run-completion reports go to these addresses (M5 notifications).
    notify_emails: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # §6.3: fixed per-tenant geolocation for reproducible AIO capture.
    # Keys: gl, hl, optional lat/lng.
    aio_geo: dict = Field(
        default_factory=lambda: {"gl": "ca", "hl": "en"}, sa_column=Column(JSON)
    )
    # Outcome attribution (panel #6): the tenant's GA4 property id (digits
    # only, e.g. "123456789"). The shared service account must be granted
    # Viewer on this property. Unset = the Outcome view stays empty.
    ga4_property_id: str | None = Field(default=None)
    # Subscription plan (pricing tier). Caps the run matrix and selects the
    # model tier (api.plans). "custom" = uncapped (default; legacy/enterprise).
    plan: str = Field(default="custom")

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
    # Per-query persona targeting (selective query×persona matrix). Each entry
    # is {"segment": str, "overlay": str}: run the persona with that segment on
    # this query, optionally appending a vertical-overlay clause to its
    # preamble. Empty = the query runs the baseline only. Only consulted when
    # the tenant has a "generic" baseline persona (selective mode); tenants
    # without one keep the full persona × query cross-product.
    persona_runs: list[dict] = Field(default_factory=list, sa_column=Column(JSON))


class Location(SQLModel, table=True):
    """A place the corpus is measured from (§SCRAPING_V3 Part 2). Mode B work
    fans out over the tenant's active locations; `country` doubles as the
    proxy-selection key so a location-based run can exit from a matching
    residential IP. A tenant with no locations uses its `aio_geo` default —
    every existing tenant is unchanged."""

    __tablename__ = "locations"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    label: str  # human name, e.g. "Toronto — Downtown"
    country: str = Field(default="ca")  # Google gl / proxy-selection key
    language: str = Field(default="en")  # hl
    latitude: float | None = None
    longitude: float | None = None
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)


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
    # Scrape hit an anti-bot wall (Cloudflare/captcha/consent), not a real
    # answer (§SCRAPING_V3 Layer 0). Kept OUT of absent/negative scoring: a
    # blocked cell is missing data, never evidence the brand isn't mentioned.
    blocked = "blocked"


class ResultVariant(StrEnum):
    # The client-facing answer (web search available to the surface).
    search = "search"
    # Classifier input only: same query/persona with search disabled — the
    # other half of the dual-query diff (§6.1). Excluded from scoring.
    nosearch = "nosearch"
    # Routing probe (§AEO-plan M2): the search tool is offered but NOT forced,
    # so whether the model searches reveals natural routing (~31% of prompts
    # are answered from training). Measurement only — excluded from scoring.
    natural = "natural"


class Result(SQLModel, table=True):
    __tablename__ = "results"  # pyright: ignore[reportAssignmentType]
    # Most dashboard reads filter (tenant_id, variant, status) together; a
    # composite index serves them directly instead of scanning the tenant's
    # whole result history and filtering variant/status in Postgres (§audit low).
    __table_args__ = (
        Index("ix_results_tenant_variant_status", "tenant_id", "variant", "status"),
    )

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
    # How many web searches the surface actually ran for this call (§AEO-plan
    # M2). On the `natural` variant this reveals whether the prompt triggered
    # search at all.
    web_search_calls: int = Field(default=0)
    status: ResultStatus = Field(default=ResultStatus.ok)
    error: str | None = None
    # Location this cell was measured from (§SCRAPING_V3 Part 2). Empty =
    # the tenant's single default location — every existing result.
    location_label: str = Field(default="", index=True)
    # The sub-queries the engine fanned out into on the way to this answer
    # (§AEO-plan M1). Populated where the surface exposes it (Gemini always,
    # OpenAI when present); empty otherwise.
    fanout_queries: list[str] = Field(default_factory=list, sa_column=Column(JSON))
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
    # The exact snippet the engine quoted from this source, where the surface
    # exposes it (Claude ≤150 chars) (§AEO-plan M6). Empty otherwise.
    cited_text: str = ""


class ConsultedSource(SQLModel, table=True):
    """A source the engine consulted but did NOT cite in the answer (§AEO-plan
    M6). Kept in its own table so it never inflates citation counts, but it is
    real competitive intel: the engines read this page and chose not to cite
    it. Populated where the surface distinguishes the two (Claude always;
    OpenAI when it returns a fuller `sources` list)."""

    __tablename__ = "consulted_sources"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    result_id: int = Field(foreign_key="results.id", index=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    url: str
    domain: str = Field(index=True)


class BrandFact(SQLModel, table=True):
    """A ground-truth fact about the tenant's brand (§AEO-plan M4), used to
    catch answers that state something false — the highest-stakes error for a
    regulated or credentialed brand. `kind` selects the check: 'numeric' (a
    tracked subject stated with a contradicting same-unit number) or
    'disallowed' (a claim that must never appear)."""

    __tablename__ = "brand_facts"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    category: str = "general"  # pricing | accreditation | leadership | coverage | …
    label: str  # human name, e.g. "Full-time MBA tuition"
    subject: str  # the topic term to detect in an answer, e.g. "tuition"
    aliases: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    kind: str = "numeric"  # numeric | disallowed
    expected: str  # correct value (numeric) or the forbidden phrase (disallowed)
    active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utcnow)


class AccuracyFinding(SQLModel, table=True):
    """A contradiction between an answer and the fact sheet (§AEO-plan M4).
    Rebuilt per-run like Mentions."""

    __tablename__ = "accuracy_findings"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    result_id: int = Field(foreign_key="results.id", index=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    fact_id: int = Field(index=True)
    category: str = ""
    severity: str = "high"
    subject: str = ""
    expected: str = ""
    stated: str = ""
    snippet: str = ""
    detail: str = ""
    detector_version: str = ""


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
    # Google AIO dimension (§5.2) — orthogonal to web-search-likelihood.
    # Defaults describe "AIO retrieval did not run".
    google_aio_triggered: bool = Field(default=False)
    google_aio_confidence: float = Field(default=0.0)
    google_aio_source_type: str = Field(default="no_aio")
    google_aio_signals: dict = Field(default_factory=dict, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow)


class VisibilityDaily(SQLModel, table=True):
    __tablename__ = "visibility_daily"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    date: str = Field(index=True)  # ISO yyyy-mm-dd (UTC day of the run)
    surface: SurfaceCode
    persona_segment: str = Field(default="", index=True)
    # Mode B location dimension: "" is the tenant's single default location (and
    # every Mode A result). A multi-location tenant gets one row per location so
    # per-location visibility isn't blended away (§audit worker-8).
    location_label: str = Field(default="", index=True)
    brand_score: float = 0.0
    # {competitor_name: score 0-100}
    competitor_scores: dict[str, float] = Field(default_factory=dict, sa_column=Column(JSON))
    # mention_rate / citation_rate / result_count for drill-down
    extras: dict = Field(default_factory=dict, sa_column=Column(JSON))
    scorer_version: str = ""
    computed_at: datetime = Field(default_factory=utcnow)


class AiReferralDaily(SQLModel, table=True):
    """Downstream outcome (panel #6): AI-referred sessions + key events by day
    and engine, pulled from the tenant's GA4 property. Keyed (tenant, date,
    engine); the pull upserts."""

    __tablename__ = "ai_referral_daily"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    date: str = Field(index=True)  # ISO yyyy-mm-dd
    engine: str = Field(index=True)  # ChatGPT | Perplexity | Claude | Gemini | …
    sessions: int = 0
    conversions: int = 0
    fetched_at: datetime = Field(default_factory=utcnow)


class Intervention(SQLModel, table=True):
    """Intervention ledger (§CMO #1): the client marks a gap-query fix as
    shipped (what/where/when); measurement then splits that query's results
    into before/after so the lift is attributable. Query snapshotted by value,
    like results — config re-imports never orphan the ledger."""

    __tablename__ = "interventions"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    query_text: str = Field(index=True)
    description: str = ""
    url: str = ""
    shipped_at: datetime = Field(default_factory=utcnow)
    created_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class PagePresence(SQLModel, table=True):
    """On-page presence audit (§focus-group #2): for each Power Page (a URL
    the engines cite), whether the brand and competitors are actually named on
    it, plus cheap citability features. Upserted per (tenant, url) by the
    nightly/on-demand crawl."""

    __tablename__ = "page_presence"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    url: str = Field(index=True)
    domain: str = ""
    status: str = "ok"  # ok | error
    http_status: int | None = None
    error: str | None = None
    brand_found: bool = False
    competitors_found: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # Citability fingerprint features (json_ld, faq_schema, has_tables,
    # recent_year_mentions, word_count).
    features: dict = Field(default_factory=dict, sa_column=Column(JSON))
    fetched_at: datetime = Field(default_factory=utcnow)


class RunSchedule(SQLModel, table=True):
    """§5.1 run_schedules. Surfaces/modes are resolved from the tenant's
    live config at fire time rather than frozen on the schedule
    (DECISIONS.md M5)."""

    __tablename__ = "run_schedules"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True, unique=True)
    cron_expr: str
    enabled: bool = Field(default=True)
    last_triggered_at: datetime | None = None
    next_run_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class RawPayload(SQLModel, table=True):
    """Postgres-backed raw-payload storage for hosts where a shared disk
    between the api and worker isn't available (e.g. Render). Selected via
    STORAGE_BACKEND=db; the file backend (VPS shared volume) is the default.
    Keyed by the same relative URI stored in results.raw_uri."""

    __tablename__ = "raw_payloads"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    uri: str = Field(unique=True, index=True)
    envelope: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class MirrorState(SQLModel, table=True):
    """Per-table high-water marks for the BigQuery mirror (§5.3)."""

    __tablename__ = "mirror_state"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    table_name: str = Field(unique=True, index=True)
    last_id: int = 0
    updated_at: datetime = Field(default_factory=utcnow)


class RecommendationStatus(StrEnum):
    open = "open"
    in_progress = "in_progress"
    done = "done"
    dismissed = "dismissed"
    resolved = "resolved"  # gap closed by the data, not by hand


class Recommendation(SQLModel, table=True):
    """§5.1 recommendations: each visibility gap mapped to a prescribed
    action by the §6.4 matrix. gap_ref is the stable identity across
    regenerations."""

    __tablename__ = "recommendations"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    gap_ref: str = Field(index=True)
    branch: str = ""  # web_search | training | aio
    action_text: str
    status: RecommendationStatus = Field(default=RecommendationStatus.open, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"  # pyright: ignore[reportAssignmentType]

    id: int | None = Field(default=None, primary_key=True)
    tenant_id: int | None = Field(default=None, foreign_key="tenants.id", index=True)
    actor: str  # email of the acting user
    action: str
    at: datetime = Field(default_factory=utcnow)
