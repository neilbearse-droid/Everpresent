"""Tenant config YAML import (§7.2 admin panel).

Replace semantics: an import swaps the tenant's brand profile, competitors,
personas, queries, and surface enablement wholesale, so re-importing a
corrected file (e.g. the real v1 configs once supplied) is always safe.
Runs/results data is never touched — those tables don't exist until M2 and
will reference config by value, not by row id, across imports.

A question that names the brand (name, alias or domain) is filed as branded
whether or not the file says so — the same rule the admin add box applies —
because a branded question in the competitive layer inflates the mention rate
(the brand nearly always appears when it is asked about)."""

import re

import yaml
from pydantic import BaseModel, Field, ValidationError
from sqlmodel import Session, delete, select

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
    # An explicit true is kept; a false on a question that names the brand is
    # overridden at import (see auto_branded_texts) and reported.
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


# "Botnia Skincare" is also called just "Botnia": a trailing generic word on
# the brand name is optional when deciding whether a question names the brand.
_GENERIC_SUFFIX = re.compile(
    r"\s+(skincare|skin care|cosmetics|beauty|labs?|inc\.?|co\.?|ltd\.?|llc|company|group)$",
    re.IGNORECASE,
)


def names_brand(text: str, names: list[str]) -> bool:
    """Whether a question names the brand: any of `names` (the brand name, its
    aliases and domains) as a whole word, case-insensitive."""
    names = names + [_GENERIC_SUFFIX.sub("", n) for n in names]
    lowered = text.lower()
    return any(re.search(rf"\b{re.escape(n.lower())}\b", lowered) for n in names if n.strip())


def brand_names(spec: BrandSpec) -> list[str]:
    return [spec.name, *spec.aliases, *spec.domains]


def auto_branded_texts(spec: TenantConfigSpec) -> list[str]:
    """Questions the file leaves unbranded but which name the brand: the import
    files them as branded. Listed in the import result so the admin sees what
    moved out of the competitive score."""
    names = brand_names(spec.brand)
    return [q.text for q in spec.queries if not q.branded and names_brand(q.text, names)]


def recheck_branded(session: Session, tenant_id: int) -> list[str]:
    """Apply the same rule to a tenant's STORED questions: flag the unbranded
    ones that name the brand (rows imported before the rule existed). Returns
    the texts flipped; the caller owns the commit. Live reads re-scope at once
    (they match results by query text); the daily rows need a reprocess."""
    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    if brand is None:
        return []
    names = [brand.brand_name, *brand.aliases, *brand.domains]
    flipped: list[str] = []
    for q in session.exec(
        select(Query).where(Query.tenant_id == tenant_id, Query.branded == False)  # noqa: E712
    ).all():
        if names_brand(q.text, names):
            q.branded = True
            session.add(q)
            flipped.append(q.text)
    return flipped


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
    auto_branded = set(auto_branded_texts(spec))
    for q in spec.queries:
        session.add(
            Query(
                tenant_id=tenant_id,
                text=q.text,
                corpus_tag=q.corpus,
                active=q.active,
                branded=q.branded or q.text in auto_branded,
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
    if auto_branded:
        summary["branded_auto"] = len(auto_branded)
    return summary
