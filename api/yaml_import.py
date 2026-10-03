"""Tenant config YAML import (§7.2 admin panel).

Replace semantics: an import swaps the tenant's brand profile, competitors,
personas, queries, and surface enablement wholesale, so re-importing a
corrected file (e.g. the real v1 configs once supplied) is always safe.
Runs/results data is never touched — those tables don't exist until M2 and
will reference config by value, not by row id, across imports."""

import yaml
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, delete

from api.models import (
    BrandFact,
    BrandProfile,
    Competitor,
    Persona,
    Query,
    SurfaceCode,
    Tenant,
    TenantSurface,
)


class BrandSpec(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class CompetitorSpec(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class PersonaSpec(BaseModel):
    name: str
    segment: str = ""
    prompt: str


class PersonaRunSpec(BaseModel):
    segment: str
    overlay: str = ""


class QuerySpec(BaseModel):
    text: str
    corpus: str = "core"
    active: bool = True
    # A branded query probes what the model says about the brand (excluded from
    # the competitive-visibility metrics; shown in the Brand-knowledge view).
    branded: bool = False
    # Personas to run on this query (selective matrix). Each item is either a
    # bare segment string or {segment, overlay}. The baseline "generic" persona
    # runs on every query implicitly and need not be listed.
    personas: list[str | PersonaRunSpec] = Field(default_factory=list)
    # Alternate wordings of the same question, rotated across repeated samples.
    paraphrases: list[str] = Field(default_factory=list)

    def persona_runs(self) -> list[dict]:
        out: list[dict] = []
        for item in self.personas:
            if isinstance(item, str):
                out.append({"segment": item, "overlay": ""})
            else:
                out.append({"segment": item.segment, "overlay": item.overlay})
        return out


class BrandFactSpec(BaseModel):
    """Ground-truth fact for the accuracy check (§AEO-plan M4). `kind` is
    'disallowed' (a phrase that must never be stated) or 'numeric' (a tracked
    subject whose same-unit number must match `expected`)."""

    label: str
    subject: str
    expected: str
    kind: str = "numeric"
    category: str = "general"
    aliases: list[str] = Field(default_factory=list)
    active: bool = True


class GeoSpec(BaseModel):
    """Where Google AI Overviews and the browser engines search from."""

    country: str = Field(pattern=r"^[a-z]{2}$")  # Google gl, e.g. "us"
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")  # Google hl


class TenantConfigSpec(BaseModel):
    brand: BrandSpec
    geo: GeoSpec | None = None
    competitors: list[CompetitorSpec] = Field(default_factory=list)
    personas: list[PersonaSpec] = Field(default_factory=list)
    queries: list[QuerySpec] = Field(default_factory=list)
    brand_facts: list[BrandFactSpec] = Field(default_factory=list)
    # None = the file doesn't mention surfaces: leave the tenant's engines and
    # approvals exactly as they are (an empty list switches them all off).
    surfaces: list[SurfaceCode] | None = None


class ConfigImportError(ValueError):
    pass


def _explain_yaml_error(text: str, exc: yaml.YAMLError) -> str:
    """Plain-language YAML error: where it broke, what the pasted text starts
    with, and the usual cause (a partial copy from a web page)."""
    mark = getattr(exc, "problem_mark", None)
    where = f" at line {mark.line + 1}" if mark is not None else ""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    hint = ""
    if first and not (first.startswith("#") or first.startswith("---") or ":" in first):
        hint = (
            f' The pasted text starts with "{first[:60]}", which isn\'t part of a config '
            "file: it looks like extra text was copied with it. Copy the file from its raw "
            "view, or use \"Load a bundled config\" instead."
        )
    return f"Not valid YAML{where}.{hint or ' Check the indentation around that line.'}"


def parse_config_yaml(text: str) -> TenantConfigSpec:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigImportError(_explain_yaml_error(text, exc)) from exc
    if not isinstance(raw, dict):
        raise ConfigImportError("Expected a YAML mapping at the top level")
    try:
        return TenantConfigSpec.model_validate(raw)
    except ValidationError as exc:
        raise ConfigImportError(str(exc)) from exc


def import_config(session: Session, tenant: Tenant, spec: TenantConfigSpec) -> dict[str, int]:
    """Caller owns the commit. Returns counts for the audit/UI summary."""
    tenant_id = tenant.id
    assert tenant_id is not None
    replaced = [BrandProfile, Competitor, Persona, Query, BrandFact]
    if spec.surfaces is not None:
        replaced.append(TenantSurface)
    for model in replaced:
        session.exec(delete(model).where(model.tenant_id == tenant_id))  # pyright: ignore[reportAttributeAccessIssue, reportCallIssue, reportArgumentType]

    session.add(
        BrandProfile(
            tenant_id=tenant_id,
            brand_name=spec.brand.name,
            aliases=spec.brand.aliases,
            domains=spec.brand.domains,
        )
    )
    for c in spec.competitors:
        session.add(
            Competitor(tenant_id=tenant_id, name=c.name, aliases=c.aliases, domains=c.domains)
        )
    for p in spec.personas:
        session.add(
            Persona(tenant_id=tenant_id, name=p.name, prompt_text=p.prompt, segment_tag=p.segment)
        )
    for q in spec.queries:
        session.add(
            Query(
                tenant_id=tenant_id,
                text=q.text,
                corpus_tag=q.corpus,
                active=q.active,
                branded=q.branded,
                persona_runs=q.persona_runs(),
                paraphrases=[p.strip() for p in q.paraphrases if p.strip()][:10],
            )
        )
    for bf in spec.brand_facts:
        session.add(
            BrandFact(
                tenant_id=tenant_id,
                category=bf.category,
                label=bf.label,
                subject=bf.subject,
                aliases=bf.aliases,
                kind=bf.kind,
                expected=bf.expected,
                active=bf.active,
            )
        )
    if spec.surfaces is not None:
        for code in SurfaceCode:
            session.add(
                TenantSurface(tenant_id=tenant_id, code=code, enabled=code in spec.surfaces)
            )
        # Importing is a superadmin action, so the surfaces it enables are also
        # governance-approved — the same lockstep the admin surface toggle
        # keeps. Without this an imported tenant shows surfaces "enabled" that
        # no run would ever dispatch (a run needs enabled AND approved).
        tenant.approved_surfaces = sorted({s.value for s in spec.surfaces})
    if spec.geo is not None:
        tenant.aio_geo = {"gl": spec.geo.country, "hl": spec.geo.language}
    session.add(tenant)

    summary = {
        "competitors": len(spec.competitors),
        "personas": len(spec.personas),
        "queries": len(spec.queries),
        "brand_facts": len(spec.brand_facts),
    }
    if spec.surfaces is not None:
        summary["surfaces_enabled"] = len(spec.surfaces)
    return summary
