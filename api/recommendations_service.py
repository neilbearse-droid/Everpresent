"""The §6.4 recommendation matrix: each visibility gap's classification maps
to a prescribed action.

  web-search-likely gaps  -> citable published content
  training-answered gaps  -> brand-corpus presence
  AIO-dominant gaps       -> the M6 branch: get cited by the sources feeding
                             Google's AI Overview

A "gap" is an active query whose latest answers never mention the brand (or,
for the AIO branch, whose AI Overview cites none of the brand's domains).
Regeneration is idempotent: gap_ref is stable, open recommendations are kept,
closed gaps auto-resolve, reopened gaps come back."""

from sqlmodel import Session, select

from api.models import (
    Mention,
    Query,
    QueryClassification,
    Recommendation,
    RecommendationStatus,
    Result,
    ResultStatus,
    ResultVariant,
    SurfaceCode,
    Tenant,
    utcnow,
)

HAND_STATUSES = {RecommendationStatus.done, RecommendationStatus.dismissed}


def _action_text(branch: str, query_text: str) -> str:
    if branch == "web_search":
        return (
            f'AI answers for "{query_text}" lean on live web search and don\'t surface the '
            "brand. Publish citable, authoritative content that answers this query directly "
            "(comparison pages, data-backed guides), and pitch the sources these answers "
            "already cite."
        )
    if branch == "training":
        return (
            f'AI answers for "{query_text}" come from model training, not live retrieval. '
            "Grow durable brand-corpus presence: authoritative mentions in widely-crawled "
            "sources (press, directories, Wikipedia-grade references) so the next training "
            "snapshots include the brand."
        )
    return (
        f'Google\'s AI Overview answers "{query_text}" without citing the brand. Target the '
        "domains the Overview cites (get listed, quoted, or referenced there) and publish "
        "content structured for AIO extraction: direct answers, clear headings, schema markup."
    )


def generate_recommendations(session: Session, tenant: Tenant) -> int:
    """Returns the number of currently-open (open/in_progress) gaps."""
    assert tenant.id is not None
    tenant_id = tenant.id

    # Gaps are a competitive concept — a branded query where the brand always
    # appears has no "visibility gap". Only non-branded queries generate
    # recommendations (branded ones live in the Brand-knowledge layer).
    queries = session.exec(
        select(Query).where(
            Query.tenant_id == tenant_id,
            Query.active == True,  # noqa: E712
            Query.branded == False,  # noqa: E712
        )
    ).all()
    # A query is classified per (query_text, surface); collapse to one row per
    # query DETERMINISTICALLY (lowest surface code wins) rather than last-wins
    # over an unordered result set, so the web_search-vs-training branch a query
    # takes doesn't flip between runs (§audit low).
    classifications: dict[str, QueryClassification] = {}
    for c in session.exec(
        select(QueryClassification)
        .where(QueryClassification.tenant_id == tenant_id)
        .order_by(QueryClassification.surface)  # pyright: ignore[reportArgumentType]
    ).all():
        classifications.setdefault(c.query_text, c)

    # Latest ok search-variant result per (query_text, surface) + brand hits.
    latest: dict[tuple[str, str], Result] = {}
    for result in session.exec(
        select(Result).where(
            Result.tenant_id == tenant_id,
            Result.variant == ResultVariant.search,
        )
    ).all():
        if result.status != ResultStatus.ok:
            continue
        key = (result.query_text, str(result.surface))
        if key not in latest or (result.id or 0) > (latest[key].id or 0):
            latest[key] = result
    latest_ids = [r.id for r in latest.values() if r.id is not None]
    brand_mentioned_ids: set[int] = set()
    if latest_ids:
        for mention in session.exec(
            select(Mention).where(
                Mention.result_id.in_(latest_ids),  # pyright: ignore[reportAttributeAccessIssue]
                Mention.entity_type == "brand",
            )
        ).all():
            brand_mentioned_ids.add(mention.result_id)

    from api.models import BrandProfile
    from engine.processing.citations import domain_is_owned

    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    brand_domains = brand.domains if brand else []

    # Which (query, branch) gaps exist right now?
    active_gaps: set[tuple[str, str]] = set()
    for query in queries:
        results_for_query = [
            r for (q_text, _s), r in latest.items() if q_text == query.text
        ]
        # Answer-surface gap: measured, and the brand never shows up.
        answer_results = [
            r for r in results_for_query if r.surface != SurfaceCode.google_aio
        ]
        answer_gap = bool(answer_results) and not any(
            r.id in brand_mentioned_ids for r in answer_results
        )
        classification = classifications.get(query.text)
        if answer_gap and classification and classification.web_search_likelihood:
            if classification.web_search_likelihood in ("very_likely", "likely"):
                active_gaps.add((query.text, "web_search"))
            elif classification.web_search_likelihood == "unlikely":
                active_gaps.add((query.text, "training"))
            # "possible" is ambiguous — no prescription (§6.4 matrix maps
            # clear classifications only).

        # AIO branch: the Overview dominates and cites none of our domains.
        if classification and classification.google_aio_source_type in (
            "aio_dominant",
            "aio_plus_organic",
        ):
            cited = classification.google_aio_signals.get("cited_domains", [])
            if not any(domain_is_owned(d, brand_domains) for d in cited):
                active_gaps.add((query.text, "aio"))

    # Reconcile with stored recommendations.
    existing = {
        r.gap_ref: r
        for r in session.exec(
            select(Recommendation).where(Recommendation.tenant_id == tenant_id)
        ).all()
    }
    open_count = 0
    for query_text, branch in sorted(active_gaps):
        gap_ref = f"query:{query_text}::branch:{branch}"
        rec = existing.pop(gap_ref, None)
        if rec is None:
            rec = Recommendation(
                tenant_id=tenant_id,
                gap_ref=gap_ref,
                branch=branch,
                action_text=_action_text(branch, query_text),
            )
            session.add(rec)
        elif rec.status == RecommendationStatus.resolved:
            rec.status = RecommendationStatus.open  # the gap came back
            rec.updated_at = utcnow()
            session.add(rec)
        if rec.status in (RecommendationStatus.open, RecommendationStatus.in_progress):
            open_count += 1

    # Anything left in `existing` no longer matches a live gap: auto-resolve
    # unless a human already closed it.
    for rec in existing.values():
        if rec.status not in HAND_STATUSES and rec.status != RecommendationStatus.resolved:
            rec.status = RecommendationStatus.resolved
            rec.updated_at = utcnow()
            session.add(rec)
    session.commit()
    return open_count
