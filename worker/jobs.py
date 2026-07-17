"""RQ job functions. Mode A dispatch lives here: the engine stays pure
retrieval/parsing/cost, the API layer stays request-shaped, and this is the
only place the two meet a database session and a provider key."""

import asyncio
import hashlib
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, timedelta
from typing import Any

from sqlmodel import Session, select

from api.config import get_settings
from api.db import get_engine
from api.models import (
    Citation,
    ConsultedSource,
    Location,
    Persona,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunMode,
    RunStatus,
    SurfaceCode,
    Tenant,
    utcnow,
)
from api.plans import cap_engines, limits_for, model_for
from api.processing_service import process_run
from api.queue import enqueue_run_mode_b
from api.runs_service import MODE_A_SURFACES, MODE_B_SURFACES, month_spend_usd
from api.storage import read_raw_envelope, write_raw_envelope
from engine.costs import (
    estimate_anthropic_cost_usd,
    estimate_gemini_cost_usd,
    estimate_mode_b_cost_usd,
    estimate_openai_cost_usd,
    estimate_perplexity_cost_usd,
)
from engine.retrievers import (
    chatgpt_web,
    claude_api,
    gemini_api,
    google_aio,
    openai_api,
    perplexity_api,
    perplexity_web,
)
from engine.retrievers.blocking import BlockedError
from engine.retrievers.stealth import ScrapeEnv


def ping() -> str:
    return "pong"


def _mark_run_failed(run_id: int, error: str) -> None:
    """Catch-all so an unexpected crash surfaces as a failed run with a reason
    instead of leaving it stuck at 'running' forever."""
    try:
        with Session(get_engine()) as session:
            run = session.get(Run, run_id)
            if run is not None and run.status in (RunStatus.pending, RunStatus.running):
                run.status = RunStatus.failed
                run.error = error[:500]
                run.finished_at = utcnow()
                session.add(run)
                session.commit()
    except Exception:  # noqa: BLE001 — never mask the original error
        pass


def run_mode_a(run_id: int) -> None:
    try:
        asyncio.run(_run_mode_a(run_id))
    except Exception as exc:  # noqa: BLE001
        _mark_run_failed(run_id, f"run crashed in Mode A: {type(exc).__name__}: {exc}")
        raise


def run_mode_b(run_id: int) -> None:
    try:
        asyncio.run(_run_mode_b(run_id))
    except Exception as exc:  # noqa: BLE001
        _mark_run_failed(run_id, f"run crashed in Mode B: {type(exc).__name__}: {exc}")
        raise


@dataclass(frozen=True)
class _AAdapter:
    """One Mode A (API) provider. All expose the same `retrieve` signature, so
    the dispatch loop routes by surface code. Adding a provider = one entry
    here plus its retriever module and cost function."""

    module: Any
    key_attr: str  # Settings attribute holding the API key
    model_attr: str  # Settings attribute holding the model id
    timeout_attr: str  # Settings attribute holding the per-call timeout
    cost_fn: Any  # (model, in_tok, out_tok, search_calls) -> usd
    env_var: str  # for the "not configured" message
    supports_nosearch: bool  # whether the search-disabled dual-query twin applies
    # Whether the search variant is FORCED (tool_choice). Only a forced surface
    # hides natural routing, so only these get the M2 natural probe; the others
    # already reveal routing via their search variant's web_search_calls.
    forces_search: bool = False


# Adding a Mode A surface = one line here plus its adapter + cost function.
A_ADAPTERS: dict[str, _AAdapter] = {
    "openai_api": _AAdapter(
        openai_api, "openai_api_key", "openai_model", "openai_timeout_s",
        estimate_openai_cost_usd, "OPENAI_API_KEY", supports_nosearch=True,
        forces_search=True,
    ),
    "perplexity_api": _AAdapter(
        perplexity_api, "perplexity_api_key", "perplexity_model", "perplexity_timeout_s",
        estimate_perplexity_cost_usd, "PERPLEXITY_API_KEY", supports_nosearch=False,
    ),
    "claude_api": _AAdapter(
        claude_api, "anthropic_api_key", "claude_model", "claude_timeout_s",
        estimate_anthropic_cost_usd, "ANTHROPIC_API_KEY", supports_nosearch=True,
    ),
    "gemini_api": _AAdapter(
        gemini_api, "gemini_api_key", "gemini_model", "gemini_timeout_s",
        estimate_gemini_cost_usd, "GEMINI_API_KEY", supports_nosearch=True,
    ),
}


# surface code -> (adapter module, model label, rate settings attribute).
# The module's `retrieve` is resolved at call time. Adding a Mode B surface =
# one line here plus its adapter module.
B_ADAPTERS: dict[str, tuple[Any, str, str]] = {
    "chatgpt_web": (chatgpt_web, "chatgpt-web", "chatgpt_web_rate_per_min"),
    "perplexity_web": (perplexity_web, "perplexity-web", "perplexity_web_rate_per_min"),
    # google_aio has its own call shape (per-query SERP capture, no persona);
    # the dispatch loop branches on it but rate limiting comes from here.
    "google_aio": (google_aio, "google-serp", "google_aio_rate_per_min"),
}


def _a_surfaces(run: Run) -> list[str]:
    return [s for s in run.surface_set if s in {str(m) for m in MODE_A_SURFACES}]


def _b_surfaces(run: Run) -> list[str]:
    return [s for s in run.surface_set if s in {str(m) for m in MODE_B_SURFACES}]


def _finalize_run(session: Session, run: Run, tenant: Tenant) -> None:
    """Single finalization after the last mode's job: status, then the
    processing pass (§6.4). A processing failure must not lose stored
    results — it is recorded on the run instead."""
    counts = run.counts
    if counts.get("capped"):
        run.status = RunStatus.capped
        run.error = run.error or (
            f"monthly spend cap reached (cap ${tenant.monthly_spend_cap_usd:.2f})"
        )
    elif counts.get("completed", 0) == 0 and (
        counts.get("failed", 0) + counts.get("blocked", 0)
    ) > 0:
        run.status = RunStatus.failed
        blocked = counts.get("blocked", 0)
        run.error = run.error or (
            f"all calls blocked ({blocked}); the exit IP is being challenged — "
            "configure a residential proxy (§SCRAPING_V3)"
            if blocked and not counts.get("failed", 0)
            else "all calls failed; see per-result errors"
        )
    else:
        run.status = RunStatus.complete
    run.finished_at = utcnow()
    session.add(run)
    session.commit()

    if counts.get("completed", 0) > 0:
        try:
            processing_counts = process_run(session, run)
            run.counts = {**run.counts, **processing_counts}
        except Exception as exc:  # noqa: BLE001
            run.error = f"processing failed: {type(exc).__name__}: {exc}"[:500]
        session.add(run)
        session.commit()

    # M5 notifications: report lands in the inbox; failure never fails a run.
    from api.notifications import notify_run_complete

    if notify_run_complete(session, run, tenant):
        run.counts = {**run.counts, "notified": len(tenant.notify_emails)}
        session.add(run)
        session.commit()


@dataclass
class _AWorkItem:
    """Plain snapshot of one (query × persona × surface × variant) cell, so the
    dispatch phase carries no ORM objects and holds no DB connection."""

    query_id: int | None
    query_text: str
    persona_id: int | None
    persona_name: str
    persona_prompt: str
    persona_segment: str
    surface: str
    variant: ResultVariant


@dataclass
class _BWorkItem:
    """Plain snapshot of one Mode B (query × persona? × surface × location)
    cell. `geo` selects locale/proxy; `location_label` is stamped on the result
    ("" = the tenant's single default location)."""

    query_id: int | None
    query_text: str
    persona_id: int | None
    persona_name: str
    persona_prompt: str
    persona_segment: str
    surface: str
    location_label: str = ""
    geo: dict[str, Any] = field(default_factory=dict)


def _base_scrape_env(settings: Any) -> ScrapeEnv:
    """The deployment-wide scrape environment (stealth + proxy + managed
    browser), before per-location geo is applied. All off by default."""
    return ScrapeEnv(
        headless=settings.chatgpt_web_headless,
        executable_path=settings.playwright_chromium_path or None,
        proxy_url=settings.scrape_proxy_url,
        proxy_map=dict(settings.scrape_proxy_map),
        cdp_endpoint=settings.scrape_cdp_endpoint,
        stealth=settings.scrape_stealth,
        block_assets=settings.scrape_block_assets,
    )


def _env_for_geo(base: ScrapeEnv, geo: dict[str, Any]) -> ScrapeEnv:
    """Clone the base env with a location's geo — country drives both locale and
    residential-proxy selection."""
    return replace(
        base,
        country=str(geo.get("gl", base.country)),
        language=str(geo.get("hl", base.language)),
        latitude=float(geo["lat"]) if "lat" in geo else None,
        longitude=float(geo["lng"]) if "lng" in geo else None,
    )


def _tenant_locations(
    session: Session, tenant_id: int, aio_geo: dict, max_locations: int | None
) -> list[tuple[str, dict]]:
    """Active locations as (label, geo) pairs, capped by the plan. A tenant with
    no locations gets one implicit entry from aio_geo with an empty label — the
    pre-location behaviour every existing tenant already has."""
    rows = session.exec(
        select(Location)
        .where(Location.tenant_id == tenant_id, Location.active == True)  # noqa: E712
        .order_by(Location.id)  # pyright: ignore[reportArgumentType]
    ).all()
    if not rows:
        return [("", dict(aio_geo))]
    if max_locations is not None:
        rows = rows[:max_locations]
    out: list[tuple[str, dict]] = []
    for loc in rows:
        geo: dict[str, Any] = {"gl": loc.country, "hl": loc.language}
        if loc.latitude is not None and loc.longitude is not None:
            geo["lat"] = loc.latitude
            geo["lng"] = loc.longitude
        out.append((loc.label, geo))
    return out


async def _dispatch_all(
    work: list[_AWorkItem],
    *,
    settings: Any,
    model_tier: str,
    concurrency: int,
    month_spent_before: float,
    cap_usd: float,
) -> tuple[list[dict[str, Any] | None], bool]:
    """Runs the (query × persona × surface) matrix with a concurrency limit,
    routing each item to its provider adapter by surface code. NO database
    connection is held here (§ connection-lifetime fix): work items are plain
    data. The spend cap is checked BEFORE each dispatch (§6.1/§9); a None slot
    means the call was withheld by the cap."""
    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    state = {"cost": 0.0, "capped": False}

    async def one(item: _AWorkItem) -> dict[str, Any] | None:
        adapter = A_ADAPTERS[item.surface]
        model = model_for(item.surface, model_tier, getattr(settings, adapter.model_attr))
        async with semaphore:
            async with lock:
                if month_spent_before + state["cost"] >= cap_usd:
                    state["capped"] = True
                    return None
            try:
                outcome = await adapter.module.retrieve(
                    item.persona_prompt,
                    item.query_text,
                    api_key=getattr(settings, adapter.key_attr),
                    model=model,
                    timeout_s=getattr(settings, adapter.timeout_attr),
                    web_search=item.variant in (ResultVariant.search, ResultVariant.natural),
                    # M2 natural probe: offer the tool but don't force it.
                    force_search=item.variant != ResultVariant.natural,
                )
            except Exception as exc:  # noqa: BLE001 — a failed call is data, not a crash
                return {"item": item, "model": model, "error": f"{type(exc).__name__}: {exc}"[:500]}
            cost = adapter.cost_fn(
                outcome.parsed.model or model,
                outcome.parsed.input_tokens,
                outcome.parsed.output_tokens,
                outcome.parsed.web_search_calls,
            )
            async with lock:
                state["cost"] += cost
            return {"item": item, "outcome": outcome, "cost": cost, "model": model}

    results = await asyncio.gather(*[one(item) for item in work])
    return list(results), state["capped"]


async def _run_mode_a(run_id: int) -> None:
    settings = get_settings()

    # Phase 1 — load config and mark running, then RELEASE the connection.
    with Session(get_engine()) as session:
        run = session.get(Run, run_id)
        if run is None or run.status != RunStatus.pending:
            return
        tenant = session.get(Tenant, run.tenant_id)
        assert tenant is not None
        tenant_slug = tenant.slug
        cap_usd = tenant.monthly_spend_cap_usd
        limits = limits_for(tenant.plan)
        a_surfaces = cap_engines(_a_surfaces(run), limits.max_engines)
        run.status = RunStatus.running
        run.started_at = utcnow()
        session.add(run)
        session.commit()

        # The plan caps the run matrix (§pricing-model): prompts, personas, and
        # whether the dual-query diagnosis twin runs. Engines are already capped
        # into surface_set at run creation.
        queries = [
            (q.id, q.text)
            for q in session.exec(
                select(Query)
                .where(Query.tenant_id == tenant.id, Query.active == True)  # noqa: E712
                .order_by(Query.id)  # pyright: ignore[reportArgumentType]
            ).all()
        ]
        personas = [
            (p.id, p.name, p.prompt_text, p.segment_tag)
            for p in session.exec(
                select(Persona).where(Persona.tenant_id == tenant.id).order_by(Persona.id)  # pyright: ignore[reportArgumentType]
            ).all()
        ]
        if limits.max_prompts is not None:
            queries = queries[: limits.max_prompts]
        if limits.max_personas is not None:
            personas = personas[: limits.max_personas]
        month_spent_before = month_spend_usd(session, run.tenant_id)

        # Diagnosis-twin cache (§cost): training knowledge is frozen between
        # model snapshots, so re-buying the nosearch twin every run measures a
        # constant. Reuse a recent twin for the same (query, surface) when the
        # stored envelope was produced by the model this plan would use now —
        # a plan/model change invalidates automatically. TTL-bounded; 0 = off.
        cached_twins: dict[tuple[str, str], tuple[str, str]] = {}
        if personas and limits.diagnosis and settings.diagnosis_refresh_days > 0:
            cutoff = utcnow() - timedelta(days=settings.diagnosis_refresh_days)
            query_texts = {qtext for (_qid, qtext) in queries}
            candidates = session.exec(
                select(Result)
                .where(
                    Result.tenant_id == tenant.id,
                    Result.variant == ResultVariant.nosearch,
                    Result.status == ResultStatus.ok,
                )
                .order_by(Result.id.desc())  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
                .limit(4000)
            ).all()
            for r in candidates:
                key = (r.query_text, str(r.surface))
                if key in cached_twins or r.query_text not in query_texts or not r.raw_uri:
                    continue
                created = r.created_at if r.created_at.tzinfo else r.created_at.replace(tzinfo=UTC)
                if created < cutoff:
                    continue
                adapter = A_ADAPTERS.get(str(r.surface))
                if adapter is None or not adapter.supports_nosearch:
                    continue
                expected = model_for(
                    str(r.surface), limits.model_tier, getattr(settings, adapter.model_attr)
                )
                envelope = read_raw_envelope(r.raw_uri, session=session) or {}
                if envelope.get("model") == expected:
                    cached_twins[key] = (r.raw_uri, r.response_hash)

    # Only dispatch surfaces whose provider key is configured; an enabled
    # surface with no key is skipped with a clear reason, never a crash. If
    # NONE of the enabled Mode A surfaces has a key, the run fails loudly.
    configured = [s for s in a_surfaces if getattr(settings, A_ADAPTERS[s].key_attr)]
    unconfigured = [s for s in a_surfaces if s not in configured]

    if not configured:
        needed = ", ".join(sorted({A_ADAPTERS[s].env_var for s in a_surfaces}))
        with Session(get_engine()) as session:
            run = session.get(Run, run_id)
            assert run is not None
            run.status = RunStatus.failed
            run.error = f"No Mode A surface is configured on this deployment. Set: {needed}"
            run.counts = {"planned": 0, "completed": 0, "failed": 0, "withheld_by_cap": 0}
            run.finished_at = utcnow()
            session.add(run)
            session.commit()
        return

    # The client-facing matrix, plus one search-disabled twin per (query,
    # surface) on the first persona — the dual-query diff the classifier
    # consumes (§6.1). The twin only applies to providers with a non-search
    # mode (Perplexity Sonar always searches). Plain snapshots: no DB
    # connection during dispatch.
    work: list[_AWorkItem] = [
        _AWorkItem(qid, qtext, pid, pname, pprompt, pseg, s, ResultVariant.search)
        for s in configured
        for (qid, qtext) in queries
        for (pid, pname, pprompt, pseg) in personas
    ]
    if personas and limits.diagnosis:
        pid0, pname0, pprompt0, pseg0 = personas[0]
        work += [
            _AWorkItem(qid, qtext, pid0, pname0, pprompt0, pseg0, s, ResultVariant.nosearch)
            for s in configured
            if A_ADAPTERS[s].supports_nosearch
            for (qid, qtext) in queries
            if (qtext, s) not in cached_twins  # twin still fresh — reuse below
        ]

    # M2 natural routing probe: an un-forced call on a deterministic fraction of
    # queries, for the surfaces that force search (only those hide routing).
    # First persona only; measurement-only, excluded from scoring.
    probe_frac = getattr(settings, "natural_probe_fraction", 0.0)
    forced_surfaces = [s for s in configured if A_ADAPTERS[s].forces_search]
    if personas and probe_frac > 0 and forced_surfaces and queries:
        n_probe = max(1, round(probe_frac * len(queries)))
        probe_queries = queries[:n_probe]
        pid0, pname0, pprompt0, pseg0 = personas[0]
        work += [
            _AWorkItem(qid, qtext, pid0, pname0, pprompt0, pseg0, s, ResultVariant.natural)
            for s in forced_surfaces
            for (qid, qtext) in probe_queries
        ]

    counts = {"planned": len(work), "completed": 0, "failed": 0, "withheld_by_cap": 0}
    if unconfigured:
        counts["skipped_unconfigured"] = len(unconfigured)
    with Session(get_engine()) as session:
        run = session.get(Run, run_id)
        assert run is not None
        run.counts = counts  # publish planned total immediately
        session.add(run)
        session.commit()

    # Phase 2 — dispatch the provider calls. NO DB CONNECTION HELD.
    outcomes, capped = await _dispatch_all(
        work,
        settings=settings,
        model_tier=limits.model_tier,
        concurrency=settings.openai_concurrency,
        month_spent_before=month_spent_before,
        cap_usd=cap_usd,
    )

    # Phase 3 — persist results with a fresh connection.
    with Session(get_engine()) as session:
        run = session.get(Run, run_id)
        tenant = session.get(Tenant, run.tenant_id) if run else None
        assert run is not None and tenant is not None

        total_cost = 0.0
        citation_count = 0
        for index, item in enumerate(outcomes):
            if item is None:
                counts["withheld_by_cap"] += 1
                continue
            wi: _AWorkItem = item["item"]
            result = Result(
                run_id=run_id,
                tenant_id=run.tenant_id,
                query_id=wi.query_id,
                persona_id=wi.persona_id,
                query_text=wi.query_text,
                persona_name=wi.persona_name,
                persona_segment=wi.persona_segment,
                surface=SurfaceCode(wi.surface),
                variant=wi.variant,
            )
            if "error" in item:
                counts["failed"] += 1
                result.status = ResultStatus.error
                result.error = item["error"]
            else:
                outcome: openai_api.RetrievalOutcome = item["outcome"]
                counts["completed"] += 1
                total_cost += item["cost"]
                result.latency_ms = outcome.latency_ms
                result.web_search_calls = outcome.parsed.web_search_calls
                result.fanout_queries = list(outcome.parsed.fanout_queries)
                result.response_hash = hashlib.sha256(
                    outcome.parsed.text.encode("utf-8")
                ).hexdigest()
                result.raw_uri = write_raw_envelope(
                    tenant_slug,
                    run_id,
                    f"result-{index:04d}",
                    {
                        "surface": wi.surface,
                        "mode": "A",
                        "variant": wi.variant,
                        "query": wi.query_text,
                        "persona": wi.persona_name,
                        "persona_prompt": wi.persona_prompt,
                        "model": item.get("model", ""),
                        "response": outcome.payload,
                        "parsed_text": outcome.parsed.text,
                        "cost_usd": item["cost"],
                    },
                    session=session,
                )
            session.add(result)
            session.flush()
            if "error" not in item and wi.variant == ResultVariant.search:
                # Citation rows are client-facing measurement data; the
                # nosearch twin is classifier input only.
                assert result.id is not None
                for parsed_citation in item["outcome"].parsed.citations:
                    citation_count += 1
                    session.add(
                        Citation(
                            result_id=result.id,
                            tenant_id=run.tenant_id,
                            url=parsed_citation.url,
                            domain=parsed_citation.domain,
                            cited_text=parsed_citation.cited_text,
                        )
                    )
                # Consulted-but-not-cited sources (§AEO-plan M6): competitive
                # intel, kept out of the citations table.
                for src in item["outcome"].parsed.consulted_sources:
                    session.add(
                        ConsultedSource(
                            result_id=result.id,
                            tenant_id=run.tenant_id,
                            url=src.url,
                            domain=src.domain,
                        )
                    )

        # Materialize cached diagnosis twins as rows in this run (same raw
        # envelope, zero provider spend) so the classifier's within-run
        # variant pairing works unchanged.
        if cached_twins and personas:
            qid_by_text = {qtext: qid for (qid, qtext) in queries}
            pid0, pname0, _pprompt0, pseg0 = personas[0]
            cloned = 0
            for (qtext, twin_surface), (uri, rhash) in cached_twins.items():
                if twin_surface not in configured:
                    continue
                session.add(
                    Result(
                        run_id=run_id,
                        tenant_id=run.tenant_id,
                        query_id=qid_by_text.get(qtext),
                        persona_id=pid0,
                        query_text=qtext,
                        persona_name=pname0,
                        persona_segment=pseg0,
                        surface=SurfaceCode(twin_surface),
                        variant=ResultVariant.nosearch,
                        raw_uri=uri,
                        response_hash=rhash,
                        latency_ms=0,
                    )
                )
                cloned += 1
            if cloned:
                counts["diagnosis_cached"] = cloned

        counts["citations"] = citation_count
        if capped:
            counts["capped"] = True
            run.error = (
                f"monthly spend cap reached (cap ${cap_usd:.2f}, "
                f"spent ${month_spent_before:.2f} before this run)"
            )
        run.counts = counts
        run.cost_usd = round(total_cost, 6)
        session.add(run)
        session.commit()

        if _b_surfaces(run):
            # Mode B runs on the Playwright container and finalizes the run
            # (single finalize + processing pass, no cross-worker races).
            enqueue_run_mode_b(run_id)
            return
        _finalize_run(session, run, tenant)


async def _run_mode_b(run_id: int) -> None:
    """Mode B (§6.2): sequential fresh-session scrapes, rate-limited per
    surface — fidelity, not volume. One cell per (query, surface) on the
    first persona (DECISIONS.md M4); no spend cap (no token cost) and no
    nosearch twin (a consumer web UI can't disable retrieval)."""
    settings = get_settings()

    # Phase 1 — load config and mark running, then RELEASE the connection.
    with Session(get_engine()) as session:
        run = session.get(Run, run_id)
        if run is None or run.status not in (RunStatus.pending, RunStatus.running):
            return
        tenant = session.get(Tenant, run.tenant_id)
        assert tenant is not None
        tenant_id = run.tenant_id
        tenant_slug = tenant.slug
        aio_geo = dict(tenant.aio_geo)
        # §9 cost governance: Mode B (scraping + SerpApi) is charged against the
        # same monthly cap as token spend. month_spent_before already includes
        # this run's Mode A cost (committed before B started).
        cap_usd = tenant.monthly_spend_cap_usd
        month_spent_before = month_spend_usd(session, tenant_id)
        limits = limits_for(tenant.plan)
        locations = _tenant_locations(session, tenant_id, aio_geo, limits.max_locations)
        b_surfaces = _b_surfaces(run)
        if run.status == RunStatus.pending:  # B-only run, not chained from A
            run.status = RunStatus.running
            run.started_at = utcnow()
            session.add(run)
            session.commit()
        queries = [
            (q.id, q.text)
            for q in session.exec(
                select(Query).where(Query.tenant_id == tenant.id, Query.active == True)  # noqa: E712
            ).all()
        ]
        personas = [
            (p.id, p.name, p.prompt_text, p.segment_tag)
            for p in session.exec(select(Persona).where(Persona.tenant_id == tenant.id)).all()
        ]
        base_counts = dict(run.counts) if run.counts else {}

    # Work fans out over locations × queries × surfaces (§SCRAPING_V3 Part 2).
    # google_aio is per (query, geo) — a SERP takes no persona (§6.3);
    # persona-framed web surfaces use the first persona (DECISIONS M4.1).
    work: list[_BWorkItem] = []
    for surface in b_surfaces:
        if surface == str(SurfaceCode.google_aio):
            work += [
                _BWorkItem(qid, qtext, None, "(serp)", "", "", surface, label, geo)
                for (label, geo) in locations
                for (qid, qtext) in queries
            ]
        elif personas:
            pid0, pname0, pprompt0, pseg0 = personas[0]
            work += [
                _BWorkItem(qid, qtext, pid0, pname0, pprompt0, pseg0, surface, label, geo)
                for (label, geo) in locations
                for (qid, qtext) in queries
            ]

    base_env = _base_scrape_env(settings)

    counts = dict(base_counts)
    counts["planned"] = counts.get("planned", 0) + len(work)
    mode_b_cost = 0.0
    capped = False

    for index, wi in enumerate(work):
        # Estimated cost of this call — charged whether it succeeds, blocks, or
        # errors (the provider/proxy resources were consumed either way).
        call_cost = estimate_mode_b_cost_usd(
            wi.surface,
            aio_provider=settings.google_aio_provider,
            serpapi_cost_per_search=settings.serpapi_cost_per_search,
            scrape_cost_per_page=settings.scrape_cost_per_page_usd,
        )
        # §9: unlike Mode A (whose token cost is only known after the call),
        # a Mode B call's cost is known upfront, so we can refuse to START a
        # call that would cross the cap — the run never exceeds it. month spend
        # already includes this run's Mode A cost.
        if month_spent_before + mode_b_cost + call_cost > cap_usd:
            capped = True
            counts["withheld_by_cap"] = counts.get("withheld_by_cap", 0) + (len(work) - index)
            break
        mode_b_cost += call_cost

        adapter_module, model_label, rate_attr = B_ADAPTERS[wi.surface]
        if index > 0:
            rate = max(float(getattr(settings, rate_attr)), 0.1)
            await asyncio.sleep(60.0 / rate)
        is_aio = wi.surface == str(SurfaceCode.google_aio)

        # The request's geo (from its location) drives locale + residential
        # proxy selection; empty geo falls back to the tenant default.
        env = _env_for_geo(base_env, wi.geo or aio_geo)

        # Phase 2 — scrape. NO DB CONNECTION HELD (a scrape can take minutes).
        error: str | None = None
        blocked = False
        outcome = None
        parsed_text = ""
        response_payload: dict[str, Any] = {}
        try:
            if is_aio:
                outcome = await google_aio.capture(
                    wi.query_text,
                    geo=wi.geo or aio_geo,
                    provider=settings.google_aio_provider,
                    serpapi_key=settings.serpapi_key,
                    headless=settings.chatgpt_web_headless,
                    timeout_s=settings.google_aio_timeout_s,
                    executable_path=settings.playwright_chromium_path or None,
                    env=env,
                )
                parsed_text = outcome.aio_text
                response_payload = {
                    "aio_summary": asdict(outcome.summary),
                    "aio_html": outcome.aio_html,
                    # §6.3: the full rendered SERP goes to object storage.
                    "page_html": outcome.page_html,
                }
            else:
                outcome = await adapter_module.retrieve(
                    wi.persona_prompt,
                    wi.query_text,
                    headless=settings.chatgpt_web_headless,
                    timeout_s=settings.chatgpt_web_timeout_s,
                    executable_path=settings.playwright_chromium_path or None,
                    env=env,
                )
                parsed_text = outcome.text
                response_payload = {"html": outcome.html_fragment}
        except BlockedError as exc:
            # §SCRAPING_V3 Layer 0: an anti-bot wall is missing data, NOT a
            # "brand absent" signal. Recorded distinctly and kept out of scoring.
            blocked = True
            error = f"blocked: {exc.reason}"
        except Exception as exc:  # noqa: BLE001 — a failed scrape is data
            error = f"{type(exc).__name__}: {exc}"[:500]

        # Phase 3 — persist this one result with a fresh connection.
        with Session(get_engine()) as session:
            result = Result(
                run_id=run_id,
                tenant_id=tenant_id,
                query_id=wi.query_id,
                persona_id=wi.persona_id,
                query_text=wi.query_text,
                persona_name=wi.persona_name,
                persona_segment=wi.persona_segment,
                surface=SurfaceCode(wi.surface),
                mode=RunMode.B,
                location_label=wi.location_label,
            )
            if blocked:
                counts["blocked"] = counts.get("blocked", 0) + 1
                result.status = ResultStatus.blocked
                result.error = error
                session.add(result)
            elif error is not None or outcome is None:
                counts["failed"] = counts.get("failed", 0) + 1
                result.status = ResultStatus.error
                result.error = error or "no outcome"
                session.add(result)
            else:
                counts["completed"] = counts.get("completed", 0) + 1
                result.latency_ms = outcome.latency_ms
                result.response_hash = hashlib.sha256(parsed_text.encode("utf-8")).hexdigest()
                result.raw_uri = write_raw_envelope(
                    tenant_slug,
                    run_id,
                    f"result-b-{index:04d}",
                    {
                        "surface": wi.surface,
                        "mode": "B",
                        "variant": "search",
                        "query": wi.query_text,
                        "persona": wi.persona_name,
                        "persona_prompt": wi.persona_prompt,
                        "model": model_label,
                        "adapter_version": adapter_module.ADAPTER_VERSION,
                        "response": response_payload,
                        "parsed_text": parsed_text,
                        "cost_usd": call_cost,
                    },
                    session=session,
                )
                session.add(result)
                session.flush()
                assert result.id is not None
                for citation in outcome.citations:
                    counts["citations"] = counts.get("citations", 0) + 1
                    session.add(
                        Citation(
                            result_id=result.id,
                            tenant_id=tenant_id,
                            url=citation.url,
                            domain=citation.domain,
                        )
                    )
            run = session.get(Run, run_id)
            if run is not None:
                run.counts = counts  # live progress each iteration
                session.add(run)
            session.commit()

    # Phase 4 — finalize with a fresh connection.
    with Session(get_engine()) as session:
        run = session.get(Run, run_id)
        tenant = session.get(Tenant, run.tenant_id) if run else None
        assert run is not None and tenant is not None
        if capped:
            counts["capped"] = True
        counts["mode_b_cost_usd"] = round(mode_b_cost, 6)
        run.counts = counts
        # Add Mode B spend to the run total (Mode A already committed it).
        run.cost_usd = round((run.cost_usd or 0.0) + mode_b_cost, 6)
        session.add(run)
        session.commit()
        _finalize_run(session, run, tenant)
