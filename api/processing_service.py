"""Post-run processing (§6.4): mention detection, citation categorization,
query classification from the dual-query diff, and the visibility_daily
rollup. Idempotent — reprocessing a run (or a day) deletes and recomputes its
derived rows, so detector/classifier upgrades can be applied to history."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_
from sqlmodel import Session, col, delete, select

from api.models import (
    AccuracyFinding,
    BrandFact,
    BrandProfile,
    Citation,
    Competitor,
    Mention,
    QueryClassification,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SponsoredUnit,
    SurfaceCode,
    Tenant,
    UntrackedMention,
    VisibilityDaily,
    utcnow,
)
from api.storage import read_raw_envelope
from engine.processing.accuracy import DETECTOR_VERSION as ACCURACY_VERSION
from engine.processing.accuracy import FactSpec, check_text
from engine.processing.aio import classify_aio_capture
from engine.processing.citations import categorize_domain, domain_is_owned
from engine.processing.classify import (
    CLASSIFIER_VERSION,
    WebSearchSignals,
    classify_web_search_likelihood,
    compute_divergence,
)
from engine.processing.entities import (
    _EXTRACTION_SYSTEM,
    EXTRACTION_VERSION,
    build_extraction_prompt,
    filter_untracked,
    parse_entities,
)
from engine.processing.mentions import DETECTOR_VERSION, detect_mentions
from engine.processing.scoring import SCORER_VERSION, ResultSignals, score_entity
from engine.retrievers.google_aio import AIOCaptureSummary


def _response_text(result: Result, session: Session) -> str:
    return _envelope(result, session).get("parsed_text", "")


def _envelope(result: Result, session: Session) -> dict:
    if not result.raw_uri:
        return {}
    return read_raw_envelope(result.raw_uri, session=session) or {}


def _backfill_fanout(result: Result, envelope: dict) -> None:
    """Older captures stored the raw response but not every engine's searches
    (Claude's were not read before m45; ChatGPT's batched `queries` neither).
    Re-read them from the stored response so reprocessing a run fills the
    fan-out without paying for new calls."""
    response = envelope.get("response")
    if not isinstance(response, dict) or not response:
        return
    surface = str(result.surface)
    try:
        if surface == "claude_api":
            from engine.retrievers.claude_api import parse_claude_payload

            found = parse_claude_payload(response).fanout_queries
        elif surface == "openai_api":
            from engine.retrievers.openai_api import parse_responses_payload

            found = parse_responses_payload(response).fanout_queries
        else:
            return
    except Exception:  # noqa: BLE001 — an odd old payload keeps what it had
        return
    if found and len(found) > len(result.fanout_queries or []):
        result.fanout_queries = list(found)


def _sponsored_units(
    envelope: dict,
    brand: tuple[str, list[str], list[str]],
    competitors: list[tuple[int | None, str, list[str], list[str]]],
) -> list[dict]:
    """Paid units stored with a capture, attributed to a tracked brand by name
    (in the unit's title/text) or by domain, else to the unit's own domain."""
    from engine.processing.ads import split_sponsored_html, sponsored_from_serp

    response = envelope.get("response") or {}
    if not isinstance(response, dict):
        return []
    units = []
    for key in ("html", "aio_html"):
        if isinstance(response.get(key), str):
            units += [u.as_dict() for u in split_sponsored_html(response[key])[1]]
    units += [u for u in response.get("sponsored") or [] if isinstance(u, dict)]
    if response.get("ads"):
        units += [u.as_dict() for u in sponsored_from_serp(response)]
    name, aliases, domains = brand
    out = []
    for u in units:
        domain = str(u.get("domain") or "")
        found = detect_mentions(f"{u.get('title', '')}\n{u.get('text', '')}", name, aliases,
                                [(cid, n, a) for cid, n, a, _d in competitors])
        if found:
            adv, kind = found[0].entity_name, found[0].entity_type
        elif domain and domain_is_owned(domain, domains):
            adv, kind = name, "brand"
        else:
            hit = next((n for _c, n, _a, ds in competitors if domain_is_owned(domain, ds)), None)
            adv, kind = (hit, "competitor") if hit and domain else (domain or "unknown", "other")
        out.append({"advertiser": adv, "advertiser_type": kind, "domain": domain,
                    "title": str(u.get("title") or "")[:200], "url": str(u.get("url") or ""),
                    "placement": str(u.get("placement") or "")})
    return out


def _extract_untracked(
    session: Session,
    run: Run,
    tenant: Tenant,
    texts: dict[int, str],
    tracked_aliases: list[str],
) -> int:
    """Governed open entity-extraction pass (§step 4). Runs only when the tenant
    opted in AND is AI-approved AND the utility model is on its allowlist AND a
    key is configured — otherwise a hard no-op (returns 0). Bounded by the
    monthly spend cap; per-call cost accrues to the run. Extraction failures on
    a single answer are swallowed (missing data, never a crashed run)."""
    from concurrent.futures import ThreadPoolExecutor

    from api.config import get_settings
    from api.runs_service import month_spend_usd
    from engine.llm import router

    if not (tenant.entity_extraction_enabled and tenant.ai_processing_approved):
        return 0
    settings = get_settings()
    model = settings.utility_model_extract
    if model not in tenant.approved_utility_models or not settings.anthropic_api_key:
        return 0

    items = [(rid, text) for rid, text in texts.items() if text]
    if not items:
        return 0

    # Cap the number of calls to what the remaining monthly budget affords.
    per_call = settings.utility_extract_cost_usd
    if per_call > 0:
        assert tenant.id is not None
        remaining = tenant.monthly_spend_cap_usd - month_spend_usd(session, tenant.id)
        affordable = max(0, int(remaining / per_call))
        items = items[:affordable]
    if not items:
        return 0

    api_key = settings.anthropic_api_key
    timeout_s = settings.utility_llm_timeout_s

    def _one(item: tuple[int, str]) -> tuple[int, list[str]]:
        rid, text = item
        try:
            raw = router.complete(
                build_extraction_prompt(text),
                model=model,
                api_key=api_key,
                system=_EXTRACTION_SYSTEM,
                max_tokens=400,
                timeout_s=timeout_s,
            )
        except Exception:  # noqa: BLE001 — a failed extraction is missing data
            return rid, []
        return rid, filter_untracked(parse_entities(raw), tracked_aliases)

    count = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for rid, names in pool.map(_one, items):
            for name in names:
                session.add(
                    UntrackedMention(
                        result_id=rid,
                        tenant_id=run.tenant_id,
                        entity_name=name,
                        detector_version=EXTRACTION_VERSION,
                    )
                )
                count += 1

    run.cost_usd = round((run.cost_usd or 0.0) + per_call * len(items), 6)
    return count


def process_run(session: Session, run: Run) -> dict[str, int]:
    assert run.id is not None
    tenant = session.get(Tenant, run.tenant_id)
    assert tenant is not None

    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == run.tenant_id)
    ).first()
    competitors = list(
        session.exec(select(Competitor).where(Competitor.tenant_id == run.tenant_id)).all()
    )
    brand_name = brand.brand_name if brand else tenant.name
    brand_aliases = brand.aliases if brand else []
    brand_domains = brand.domains if brand else []
    competitor_domains = [d for c in competitors for d in c.domains]
    competitor_specs = [(c.id, c.name, c.aliases) for c in competitors]

    results = list(session.exec(select(Result).where(Result.run_id == run.id)).all())
    search_results = [
        r for r in results if r.variant == ResultVariant.search and r.status == ResultStatus.ok
    ]
    nosearch_by_key = {
        (r.query_text, r.persona_name, r.surface): r
        for r in results
        if r.variant == ResultVariant.nosearch and r.status == ResultStatus.ok
    }

    # Ground-truth fact sheet for the accuracy check (§AEO-plan M4); empty is
    # fine — the check degrades to "no facts on file".
    fact_specs = [
        FactSpec(id=f.id, category=f.category, label=f.label, subject=f.subject,
                 aliases=list(f.aliases or []), kind=f.kind, expected=f.expected)
        for f in session.exec(
            select(BrandFact).where(
                BrandFact.tenant_id == run.tenant_id, BrandFact.active == True  # noqa: E712
            )
        ).all()
        if f.id is not None
    ]

    # Idempotent reprocess: clear this run's derived rows.
    result_ids = [r.id for r in results if r.id is not None]
    if result_ids:
        session.exec(delete(Mention).where(Mention.result_id.in_(result_ids)))  # pyright: ignore[reportAttributeAccessIssue, reportCallIssue, reportArgumentType]
        session.exec(delete(AccuracyFinding).where(AccuracyFinding.result_id.in_(result_ids)))  # pyright: ignore[reportAttributeAccessIssue, reportCallIssue, reportArgumentType]
        session.exec(delete(UntrackedMention).where(UntrackedMention.result_id.in_(result_ids)))  # pyright: ignore[reportAttributeAccessIssue, reportCallIssue, reportArgumentType]
        session.exec(delete(SponsoredUnit).where(SponsoredUnit.result_id.in_(result_ids)))  # pyright: ignore[reportAttributeAccessIssue, reportCallIssue, reportArgumentType]

    counts = {"mentions": 0, "classified_queries": 0, "citations_categorized": 0,
              "accuracy_findings": 0, "sponsored_units": 0}
    ad_brand = (brand_name, brand_aliases, brand_domains)
    ad_competitors = [(c.id, c.name, c.aliases, c.domains) for c in competitors]

    texts: dict[int, str] = {}
    for result in search_results:
        assert result.id is not None
        envelope = _envelope(result, session)
        text = envelope.get("parsed_text", "")
        _backfill_fanout(result, envelope)
        texts[result.id] = text
        for unit in _sponsored_units(envelope, ad_brand, ad_competitors):
            counts["sponsored_units"] += 1
            session.add(SponsoredUnit(result_id=result.id, tenant_id=run.tenant_id, **unit))
        for detected in detect_mentions(text, brand_name, brand_aliases, competitor_specs):
            counts["mentions"] += 1
            session.add(
                Mention(
                    result_id=result.id,
                    tenant_id=run.tenant_id,
                    entity_type=detected.entity_type,
                    entity_name=detected.entity_name,
                    competitor_id=detected.competitor_id,
                    position=detected.position,
                    rank=detected.rank,
                    sentiment=detected.sentiment,
                    context_snippet=detected.context_snippet,
                    detector_version=DETECTOR_VERSION,
                )
            )
        # Accuracy: does this answer state anything the fact sheet contradicts?
        for hit in check_text(text, fact_specs):
            counts["accuracy_findings"] += 1
            session.add(
                AccuracyFinding(
                    result_id=result.id,
                    tenant_id=run.tenant_id,
                    fact_id=hit.fact_id,
                    category=hit.category,
                    severity=hit.severity,
                    subject=hit.subject,
                    expected=hit.expected,
                    stated=hit.stated,
                    snippet=hit.snippet,
                    detail=hit.detail,
                    detector_version=ACCURACY_VERSION,
                )
            )

    # Open out-of-list entity extraction (§step 4 — the whitespace slide).
    # Governed utility-LLM pass; opt-in, cost-bounded, and a hard no-op for
    # tenants that haven't enabled it, so existing tenants are untouched.
    tracked_aliases = [brand_name, *brand_aliases]
    for _cid, cname, caliases in competitor_specs:
        tracked_aliases.append(cname)
        tracked_aliases.extend(caliases)
    counts["untracked_mentions"] = _extract_untracked(
        session, run, tenant, texts, tracked_aliases
    )

    # Citation categorization (all variants — cheap and harmless). Bucket by
    # result_id in the same pass so the twin/AIO loops below can index in memory
    # instead of issuing one SELECT per result (§audit low, N+1).
    citations_by_result: dict[int, list[Citation]] = defaultdict(list)
    if result_ids:
        for citation in session.exec(
            select(Citation).where(Citation.result_id.in_(result_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            citation.source_category = categorize_domain(
                citation.domain, brand_domains, competitor_domains
            )
            session.add(citation)
            citations_by_result[citation.result_id].append(citation)
            counts["citations_categorized"] += 1

    # Query classification from the dual-query diff. The nosearch variant ran
    # on one persona per (query, surface); classify against that persona's
    # search-enabled twin.
    for (query_text, persona_name, surface), nosearch in nosearch_by_key.items():
        twin = next(
            (
                r
                for r in search_results
                if r.query_text == query_text
                and r.persona_name == persona_name
                and r.surface == surface
            ),
            None,
        )
        if twin is None or twin.id is None:
            continue
        citation_count = len(citations_by_result.get(twin.id, ()))
        signals = WebSearchSignals(
            # Use the count each adapter's parser already stored on the row
            # (§audit H3). The old envelope-scan only understood OpenAI's shape
            # and returned 0 for Gemini/Claude/Perplexity, biasing them toward
            # "did not search".
            web_search_calls=twin.web_search_calls,
            citation_count=citation_count,
            divergence=compute_divergence(
                texts.get(twin.id, ""), _response_text(nosearch, session)
            ),
        )
        bucket = classify_web_search_likelihood(signals)
        existing = session.exec(
            select(QueryClassification).where(
                QueryClassification.tenant_id == run.tenant_id,
                QueryClassification.query_text == query_text,
                QueryClassification.surface == surface,
            )
        ).first()
        if existing is None:
            existing = QueryClassification(
                tenant_id=run.tenant_id, query_text=query_text, surface=surface,
                web_search_likelihood=bucket,
            )
        existing.query_id = twin.query_id
        existing.web_search_likelihood = bucket
        existing.signals = {
            "web_search_calls": signals.web_search_calls,
            "citation_count": signals.citation_count,
            "divergence": signals.divergence,
        }
        existing.classifier_version = CLASSIFIER_VERSION
        existing.run_id = run.id
        existing.updated_at = utcnow()
        session.add(existing)
        counts["classified_queries"] += 1

    # Google AIO dimension (§5.2) — orthogonal to web-search-likelihood.
    # Each captured SERP classifies onto the query's classification row(s);
    # queries with no row yet get one keyed to the google_aio surface.
    #
    # A multi-location run captures the same query's SERP once per location, but
    # QueryClassification is keyed per (query, surface), not per location — so
    # classify ONE representative capture per query (§audit worker-4). Without
    # this, each location's capture overwrites the previous one (last-location-
    # wins) and aio_classified is inflated N×. Representative = the tenant's
    # default-location capture when present, else the earliest by id.
    aio_reps: dict[str, Result] = {}
    for result in search_results:
        if result.surface != SurfaceCode.google_aio or not result.raw_uri:
            continue
        current = aio_reps.get(result.query_text)
        if current is None:
            aio_reps[result.query_text] = result
            continue
        prefer_new = (result.location_label == "" and current.location_label != "") or (
            (result.location_label == "") == (current.location_label == "")
            and (result.id or 0) < (current.id or 0)
        )
        if prefer_new:
            aio_reps[result.query_text] = result

    for result in aio_reps.values():
        envelope = read_raw_envelope(result.raw_uri, session=session) or {}
        summary_dict = (envelope.get("response") or {}).get("aio_summary") or {}
        summary = (
            AIOCaptureSummary(**summary_dict) if summary_dict else AIOCaptureSummary(ran=False)
        )
        assert result.id is not None
        cited_urls = [c.url for c in citations_by_result.get(result.id, ())]
        signal = classify_aio_capture(summary, cited_urls)
        rows = list(
            session.exec(
                select(QueryClassification).where(
                    QueryClassification.tenant_id == run.tenant_id,
                    QueryClassification.query_text == result.query_text,
                )
            ).all()
        )
        if not rows:
            rows = [
                QueryClassification(
                    tenant_id=run.tenant_id,
                    query_id=result.query_id,
                    query_text=result.query_text,
                    surface=SurfaceCode.google_aio,
                    web_search_likelihood="",
                )
            ]
        for row in rows:
            row.google_aio_triggered = signal.triggered
            row.google_aio_confidence = signal.confidence
            row.google_aio_source_type = str(signal.source_type)
            row.google_aio_signals = {
                "cited_urls": signal.cited_urls,
                "cited_domains": signal.cited_domains,
                "classifier_version": signal.classifier_version,
                "aio_position_index": summary.aio_position_index,
                "aio_text_len": summary.aio_text_len,
                "expanded": summary.expanded,
                "organic_count": summary.organic_count,
            }
            row.run_id = run.id
            row.updated_at = utcnow()
            session.add(row)
        counts["aio_classified"] = counts.get("aio_classified", 0) + 1

    # Fan-out shards (§FANOUT_SCORECARD M25b): harvest this run's sub-queries so
    # the scorecard is longitudinal and the worker can re-probe the top ones.
    from api.config import get_settings
    from api.fanout_service import harvest_shards

    shard_count = harvest_shards(
        session, run, search_results, ttl_days=get_settings().fanout_reprobe_ttl_days
    )
    if shard_count:
        counts["fanout_shards"] = shard_count

    session.commit()
    rollup_day(session, run.tenant_id, _run_day(run), include_run_id=run.id)

    # §6.4 recommendation matrix, regenerated from the fresh state.
    from api.recommendations_service import generate_recommendations

    tenant_obj = session.get(Tenant, run.tenant_id)
    assert tenant_obj is not None
    counts["recommendations"] = generate_recommendations(session, tenant_obj)
    return counts


def _run_day(run: Run) -> str:
    stamp = run.finished_at or run.started_at or datetime.now(UTC)
    return stamp.date().isoformat()


def rollup_day(
    session: Session, tenant_id: int, day: str, include_run_id: int | None = None
) -> int:
    """Recompute visibility_daily for every (surface, segment) group of the
    tenant's search-variant results finished on `day` — across all of that
    day's runs, so repeated runs don't double-count."""
    # Prefilter in SQL to runs plausibly on `day` instead of scanning the
    # tenant's entire run history every rollup (§audit low). A run whose
    # _run_day == day either finished on that day (finished_at in the window) or
    # has no finished_at (fallback to started_at/now) — so this is a safe
    # superset; the exact _run_day check below refines it.
    day_start = datetime.fromisoformat(day).replace(tzinfo=UTC)
    day_end = day_start + timedelta(days=1)
    candidate_runs = session.exec(
        select(Run).where(
            Run.tenant_id == tenant_id,
            or_(
                col(Run.finished_at).is_(None),
                and_(col(Run.finished_at) >= day_start, col(Run.finished_at) < day_end),
            ),
        )
    ).all()
    # Only runs whose processing has produced mentions: finished runs, minus
    # any whose processing failed. A run still in Mode B (or stranded
    # "running") has results but no mentions yet, and would read as "brand not
    # mentioned". `include_run_id` is the run being processed right now.
    runs_of_day = [
        r
        for r in candidate_runs
        if _run_day(r) == day
        and r.id is not None
        and (
            r.id == include_run_id
            or (
                r.status in (RunStatus.complete, RunStatus.capped)
                and not (r.error or "").startswith("processing failed")
            )
        )
    ]
    run_ids = [r.id for r in runs_of_day]
    session.exec(
        delete(VisibilityDaily).where(  # pyright: ignore[reportCallIssue]
            VisibilityDaily.tenant_id == tenant_id,  # pyright: ignore[reportArgumentType]
            VisibilityDaily.date == day,  # pyright: ignore[reportArgumentType]
        )
    )
    if not run_ids:
        session.commit()
        return 0

    # visibility_daily is the competitive-visibility layer, so branded queries
    # (the brand always appears) are excluded — they'd inflate the score and
    # share of voice. They're measured in the Brand-knowledge layer instead.
    # Agent prompts are their own category (Agent picks) and are left out too.
    from api.dashboards.common import _off_score_query_texts

    branded = _off_score_query_texts(session, tenant_id)
    results = [
        r
        for r in session.exec(
            select(Result).where(Result.run_id.in_(run_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all()
        if r.variant == ResultVariant.search
        and r.status == ResultStatus.ok
        and r.query_text not in branded
    ]
    competitors = list(
        session.exec(select(Competitor).where(Competitor.tenant_id == tenant_id)).all()
    )
    result_ids = [r.id for r in results if r.id is not None]
    mentions_by_result: dict[int, list[Mention]] = defaultdict(list)
    citations_by_result: dict[int, list[Citation]] = defaultdict(list)
    if result_ids:
        for m in session.exec(
            select(Mention).where(Mention.result_id.in_(result_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            mentions_by_result[m.result_id].append(m)
        for c in session.exec(
            select(Citation).where(Citation.result_id.in_(result_ids))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            citations_by_result[c.result_id].append(c)

    # Keyed by (surface, segment, location) so a multi-location tenant keeps a
    # per-location score instead of blending all locations into one (§audit
    # worker-8). Mode A results carry location_label "" — their grouping is
    # unchanged.
    groups: dict[tuple[SurfaceCode, str, str], list[Result]] = defaultdict(list)
    for r in results:
        groups[(r.surface, r.persona_segment, r.location_label)].append(r)

    brand_profile = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
    ).first()
    tenant = session.get(Tenant, tenant_id)
    assert tenant is not None
    brand_name = brand_profile.brand_name if brand_profile else tenant.name
    brand_domains = brand_profile.domains if brand_profile else []

    def entity_signals(
        group: list[Result],
        name: str,
        owned_domains: list[str],
        *,
        is_brand: bool,
    ) -> list[ResultSignals]:
        def matches(m: Mention) -> bool:
            # There is exactly one brand, so match it by type: a renamed brand
            # must not zero out mentions stored under the old name. Competitors
            # match by name (their ids change on every config re-import).
            if is_brand:
                return m.entity_type == "brand"
            return m.entity_type != "brand" and m.entity_name == name

        signals = []
        for r in group:
            assert r.id is not None
            mention = next((m for m in mentions_by_result[r.id] if matches(m)), None)
            cited = any(
                domain_is_owned(c.domain, owned_domains) for c in citations_by_result[r.id]
            )
            signals.append(
                ResultSignals(mention_rank=mention.rank if mention else None, cited=cited)
            )
        return signals

    rows = 0
    for (surface, segment, location_label), group in sorted(groups.items()):
        brand_score = score_entity(entity_signals(group, brand_name, brand_domains, is_brand=True))
        competitor_scores = {
            c.name: score_entity(entity_signals(group, c.name, c.domains, is_brand=False)).score
            for c in competitors
        }
        session.add(
            VisibilityDaily(
                tenant_id=tenant_id,
                date=day,
                surface=surface,
                persona_segment=segment,
                location_label=location_label,
                brand_score=brand_score.score,
                competitor_scores=competitor_scores,
                extras={
                    "mention_rate": brand_score.mention_rate,
                    "citation_rate": brand_score.citation_rate,
                    "result_count": brand_score.result_count,
                },
                scorer_version=SCORER_VERSION,
            )
        )
        rows += 1
    session.commit()
    return rows


def reprocess_tenant_job(tenant_id: int) -> dict[str, int]:
    """Re-run processing over every completed run of a tenant, oldest first
    (RQ entry point). Applies detector and parser upgrades, such as newly read
    fan-out searches, to history without paying for new answers."""
    from api.db import get_engine

    done = failed = 0
    with Session(get_engine()) as session:
        run_ids = [r.id for r in session.exec(
            select(Run).where(Run.tenant_id == tenant_id, Run.status == RunStatus.complete)
            .order_by(col(Run.id))
        ).all()]
        for run_id in run_ids:
            run = session.get(Run, run_id)
            if run is None:
                continue
            try:
                run.counts = {**run.counts, **process_run(session, run)}
                session.add(run)
                session.commit()
                done += 1
            except Exception:  # noqa: BLE001 — one bad run must not stop the rest
                session.rollback()
                failed += 1
    return {"reprocessed": done, "failed": failed}
