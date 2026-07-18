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
    # Personas to run on this query (selective matrix). Each item is either a
    # bare segment string or {segment, overlay}. The baseline "generic" persona
    # runs on every query implicitly and need not be listed.
    personas: list[str | PersonaRunSpec] = Field(default_factory=list)

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


class TenantConfigSpec(BaseModel):
    brand: BrandSpec
    competitors: list[CompetitorSpec] = Field(default_factory=list)
    personas: list[PersonaSpec] = Field(default_factory=list)
    queries: list[QuerySpec] = Field(default_factory=list)
    brand_facts: list[BrandFactSpec] = Field(default_factory=list)
    surfaces: list[SurfaceCode] = Field(default_factory=list)


class ConfigImportError(ValueError):
    pass


def parse_config_yaml(text: str) -> TenantConfigSpec:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigImportError(f"Not valid YAML: {exc}") from exc
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
    for model in (BrandProfile, Competitor, Persona, Query, BrandFact, TenantSurface):
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
                persona_runs=q.persona_runs(),
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
    for code in SurfaceCode:
        session.add(TenantSurface(tenant_id=tenant_id, code=code, enabled=code in spec.surfaces))

    return {
        "competitors": len(spec.competitors),
        "personas": len(spec.personas),
        "queries": len(spec.queries),
        "brand_facts": len(spec.brand_facts),
        "surfaces_enabled": len(spec.surfaces),
    }
