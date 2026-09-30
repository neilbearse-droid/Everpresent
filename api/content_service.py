"""Content generation (§step 5 — the closed loop end).

Turns a detected gap — a factual-accuracy error, or a fan-out shard the brand
lost (M25c) — into a publishable draft via the governed utility-LLM
(engine/llm router, draft model). This is the step that separates 'we see the
wrong answer' from 'here is the content that fixes it' — the demo's wow moment
(Q3: 'is domain privacy free with GoDaddy?').

Governance: identical bar to entity extraction — the tenant must be
ai_processing_approved AND have the draft model on approved_utility_models AND a
key configured; otherwise ContentGenUnavailable is raised (the caller renders a
clear reason, not a crash)."""

from sqlmodel import Session, select

from api.config import get_settings
from api.dashboards_service import _surface_label
from api.models import (
    AccuracyFinding,
    BrandFact,
    BrandProfile,
    Citation,
    Competitor,
    ContentDraft,
    ContentDraftStatus,
    FanoutShard,
    Result,
    Tenant,
    utcnow,
)
from api.storage import read_raw_envelope
from engine.content.draft import (
    DRAFT_SYSTEM,
    DRAFT_VERSION,
    AccuracyGapContext,
    ShardGapContext,
    build_accuracy_draft_prompt,
    build_shard_draft_prompt,
    parse_draft,
)
from engine.llm import router
from engine.processing.mentions import detect_mentions


class ContentGenUnavailable(RuntimeError):
    """Content generation isn't available for this tenant/config — a governance
    or configuration condition, surfaced to the caller as a clear message."""


def _require_governed_draft_model(tenant: Tenant) -> tuple[str, str]:
    """The (model, api_key) for a governed draft call, or raise with the reason."""
    settings = get_settings()
    if not tenant.ai_processing_approved:
        raise ContentGenUnavailable("AI processing is not approved for this tenant")
    model = settings.utility_model_draft
    if model not in tenant.approved_utility_models:
        raise ContentGenUnavailable(f"{model} is not on this tenant's approved utility models")
    if not settings.anthropic_api_key:
        raise ContentGenUnavailable("no Anthropic API key configured")
    return model, settings.anthropic_api_key


def _accuracy_context(session: Session, tenant: Tenant, fact: BrandFact) -> AccuracyGapContext:
    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant.id)
    ).first()
    brand_name = brand.brand_name if brand else tenant.name

    findings = session.exec(
        select(AccuracyFinding).where(
            AccuracyFinding.tenant_id == tenant.id,
            AccuracyFinding.fact_id == fact.id,
        )
    ).all()
    engines: set[str] = set()
    snippets: list[str] = []
    stated: set[str] = set()
    result_ids: list[int] = []
    for f in findings:
        result = session.get(Result, f.result_id)
        if result is not None:
            engines.add(_surface_label(str(result.surface)))
            if result.id is not None:
                result_ids.append(result.id)
        if f.snippet:
            snippets.append(f.snippet)
        if f.stated:
            stated.add(f.stated)

    domains: list[str] = []
    seen_domains: set[str] = set()
    if result_ids:
        for c in session.exec(
            select(Citation).where(Citation.result_id.in_(result_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            if c.domain and c.domain not in seen_domains:
                seen_domains.add(c.domain)
                domains.append(c.domain)

    # disallowed: `expected` is the forbidden (wrong) phrase, `label` describes
    # the truth. numeric: `expected` is the correct value; the wrong values come
    # from the findings' stated numbers.
    if fact.kind == "disallowed":
        wrong_claim = fact.expected
        correct_value = fact.label
    else:
        wrong_claim = ", ".join(sorted(stated)) or "an incorrect value"
        correct_value = fact.expected

    return AccuracyGapContext(
        brand_name=brand_name,
        subject=fact.subject,
        wrong_claim=wrong_claim,
        correct_value=correct_value,
        engines=sorted(engines),
        snippets=snippets,
        source_domains=domains[:8],
    )


def generate_accuracy_draft(session: Session, tenant: Tenant, fact_id: int) -> ContentDraft:
    """Generate (or regenerate) the corrective content draft for an accuracy
    fact. Idempotent per (tenant, fact): replaces the existing draft for that
    source so the loop can be re-run without piling up duplicates."""
    assert tenant.id is not None
    fact = session.get(BrandFact, fact_id)
    if fact is None or fact.tenant_id != tenant.id:
        raise ContentGenUnavailable("no such fact for this tenant")
    model, api_key = _require_governed_draft_model(tenant)

    ctx = _accuracy_context(session, tenant, fact)
    return _draft(
        session, tenant, model, api_key,
        prompt=build_accuracy_draft_prompt(ctx),
        source_kind="accuracy",
        source_ref=f"fact:{fact_id}",
        fallback_title=f"Setting the record straight: {fact.subject}",
    )


def _draft(
    session: Session,
    tenant: Tenant,
    model: str,
    api_key: str,
    *,
    prompt: str,
    source_kind: str,
    source_ref: str,
    fallback_title: str,
) -> ContentDraft:
    """One governed draft call, upserted per (tenant, source_kind, source_ref)
    so regenerating replaces rather than piles up duplicates."""
    assert tenant.id is not None
    raw = router.complete(
        prompt,
        model=model,
        api_key=api_key,
        system=DRAFT_SYSTEM,
        max_tokens=1600,
        timeout_s=get_settings().utility_llm_timeout_s,
    )
    title, body = parse_draft(raw)
    draft = session.exec(
        select(ContentDraft).where(
            ContentDraft.tenant_id == tenant.id,
            ContentDraft.source_kind == source_kind,
            ContentDraft.source_ref == source_ref,
        )
    ).first()
    if draft is None:
        draft = ContentDraft(tenant_id=tenant.id, source_kind=source_kind, source_ref=source_ref)
    draft.title = title or fallback_title
    draft.body = body
    draft.model = f"{model}/{DRAFT_VERSION}"
    draft.status = ContentDraftStatus.draft
    draft.updated_at = utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


def _shard_context(session: Session, tenant: Tenant, shard: FanoutShard) -> ShardGapContext:
    """What the drafter needs about a lost shard, read from the re-probe answer
    itself: how it framed the winners and which sources it cited."""
    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant.id)
    ).first()
    brand_name = brand.brand_name if brand else tenant.name
    winners = list(shard.winners or [])

    snippets: list[str] = []
    domains: list[str] = []
    probe = session.get(Result, shard.probe_result_id) if shard.probe_result_id else None
    if probe is not None and probe.raw_uri:
        envelope = read_raw_envelope(probe.raw_uri, session=session) or {}
        comps = [
            (c.id, c.name, list(c.aliases))
            for c in session.exec(
                select(Competitor).where(
                    Competitor.tenant_id == tenant.id,
                    Competitor.name.in_(winners),  # pyright: ignore[reportAttributeAccessIssue]
                )
            ).all()
        ]
        for m in detect_mentions(envelope.get("parsed_text", ""), brand_name, [], comps):
            if m.entity_type == "competitor" and m.context_snippet:
                snippets.append(m.context_snippet)
        for c in envelope.get("citations") or []:
            domain = c.get("domain", "")
            if domain and domain not in domains:
                domains.append(domain)

    return ShardGapContext(
        brand_name=brand_name,
        parent_query=shard.parent_query_text,
        shard_text=shard.shard_text,
        winners=winners,
        engine=_surface_label(shard.probe_surface) if shard.probe_surface else "",
        snippets=snippets,
        source_domains=domains[:8],
    )


def generate_shard_draft(session: Session, tenant: Tenant, shard_id: int) -> ContentDraft:
    """Close the loop on a lost fan-out shard (§FANOUT_SCORECARD M25c): a brief
    + draft that answers the sub-query the engine searched. Only for a shard a
    re-probe actually measured as a miss — never for an unresolved one. Keyed
    by the shard's normalized text so the same shard across runs shares one
    draft."""
    assert tenant.id is not None
    shard = session.get(FanoutShard, shard_id)
    if shard is None or shard.tenant_id != tenant.id:
        raise ContentGenUnavailable("no such shard for this tenant")
    if shard.source != "reprobed" or shard.brand_present is not False:
        raise ContentGenUnavailable("only a re-probed shard you're absent from gets a brief")
    model, api_key = _require_governed_draft_model(tenant)

    ctx = _shard_context(session, tenant, shard)
    return _draft(
        session, tenant, model, api_key,
        prompt=build_shard_draft_prompt(ctx),
        source_kind="fanout",
        source_ref=f"shard:{shard.shard_norm}",
        fallback_title=f"Brief: {shard.shard_text}",
    )


def list_drafts(session: Session, tenant_id: int) -> list[ContentDraft]:
    return list(
        session.exec(
            select(ContentDraft)
            .where(ContentDraft.tenant_id == tenant_id)
            .order_by(ContentDraft.updated_at.desc())  # pyright: ignore[reportAttributeAccessIssue]
        ).all()
    )
