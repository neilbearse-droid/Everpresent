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
from api.fanout_service import (
    ShardCandidate,
    evaluate_probe,
    names_present,
    probe_surface_for,
    select_candidates,
    shard_priority,
)
from api.models import (
    BrandProfile,
    Citation,
    Competitor,
    ConsultedSource,
    FanoutShard,
    Location,
    Mention,
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
    copilot_web,
    gemini_api,
    google_ai_mode,
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
        # A Mode B crash must not strand Mode A's already-committed results
        # unprocessed (§audit worker-3). Salvage them: run the normal finalize
        # (status + processing pass) over whatever completed, recording the
        # error. Only if there is nothing to salvage do we mark the run failed.
        salvaged = _finalize_after_crash(
            run_id, f"Mode B crashed: {type(exc).__name__}: {exc}"
        )
        if not salvaged:
            _mark_run_failed(run_id, f"run crashed in Mode B: {type(exc).__name__}: {exc}")
        raise


def _finalize_after_crash(run_id: int, error: str) -> bool:
    """Salvage a run after a mid-run crash: if any results already completed,
    record the error and run the normal finalize (status + processing pass) so
    a partial-mode failure doesn't discard committed results. Returns True when
    it finalized, False when there was nothing to salvage."""
    try:
        with Session(get_engine()) as session:
            run = session.get(Run, run_id)
            if run is None or run.status not in (RunStatus.pending, RunStatus.running):
                return False
            tenant = session.get(Tenant, run.tenant_id)
            if tenant is None or (run.counts or {}).get("completed", 0) == 0:
                return False
            run.error = (run.error or error)[:500]
            _finalize_run(session, run, tenant)
            return True
    except Exception:  # noqa: BLE001 — fall back to plain failure marking
        return False


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
        # The Agent API makes search an explicit tool, so the search-disabled
        # (training-only) twin works for Perplexity too since the migration.
        estimate_perplexity_cost_usd, "PERPLEXITY_API_KEY", supports_nosearch=True,
        forces_search=True,
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


# surface code -> (adapter module, model label, rate attr, timeout attr).
# The module's `retrieve` is resolved at call time. Adding a Mode B surface =
# one line here plus its adapter module.
B_ADAPTERS: dict[str, tuple[Any, str, str, str]] = {
    "chatgpt_web": (
        chatgpt_web, "chatgpt-web", "chatgpt_web_rate_per_min", "chatgpt_web_timeout_s",
    ),
    "perplexity_web": (
        perplexity_web, "perplexity-web", "perplexity_web_rate_per_min", "chatgpt_web_timeout_s",
    ),
    "copilot_web": (
        copilot_web, "copilot-web", "copilot_web_rate_per_min", "copilot_web_timeout_s",
    ),
    # google_aio has its own call shape (per-query SERP capture, no persona);
    # the dispatch loop branches on it but rate limiting comes from here.
    "google_aio": (google_aio, "google-serp", "google_aio_rate_per_min", "google_aio_timeout_s"),
    # AI Mode is a SERP-style capture too (SerpApi, per query, no persona).
    "google_ai_mode": (
        google_ai_mode, "google-ai-mode", "google_ai_mode_rate_per_min",
        "google_ai_mode_timeout_s",
    ),
}


# Extra seconds a Mode B call gets beyond its configured timeout (browser
# launch and teardown) before the dispatch loop gives up on it.
_B_TIMEOUT_GRACE_S = 60
_B_BREAKER_THRESHOLD = 5  # consecutive failures before a surface is skipped

# Conservative per-call upper bounds for the cap reservation (§audit H6). A
# real call rarely exceeds these; over-reserving errs toward withholding early.
_EST_INPUT_TOKENS = 3000
_EST_OUTPUT_TOKENS = 1500
_EST_SEARCH_CALLS = 4


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
            # Discard the half-applied derived rows (and any failed DB
            # transaction) before recording the error on a fresh read.
            session.rollback()
            session.refresh(run)
            run.error = f"processing failed: {type(exc).__name__}: {exc}"[:500]
        session.add(run)
        session.commit()

    # M5 notifications: report lands in the inbox; failure never fails a run.
    from api.notifications import notify_run_complete

    if notify_run_complete(session, run, tenant):
        run.counts = {**run.counts, "notified": len(tenant.notify_emails)}
        session.add(run)
        session.commit()

    # Fan-out re-probe (§FANOUT_SCORECARD M25b) runs as its own job, queued
    # last so nothing here writes run.counts after it starts. Opt-in,
    # plan-gated, and it never fails the run it follows.
    if (
        tenant.fanout_reprobe_enabled
        and limits_for(tenant.plan).shard_probes_per_run > 0
        and run.counts.get("fanout_shards", 0) > 0
        and not run.counts.get("capped")
    ):
        from api import queue

        try:
            queue.enqueue_fanout_reprobe(run.id)  # pyright: ignore[reportArgumentType]
            run.counts = {**run.counts, "fanout_reprobe_queued": 1}
        except Exception:  # noqa: BLE001 — a queue hiccup must not fail the run
            run.counts = {**run.counts, "fanout_reprobe_enqueue_failed": 1}
        session.add(run)
        session.commit()


def tenant_for_handoff(session: Session, run: Run) -> Tenant:
    tenant = session.get(Tenant, run.tenant_id)
    assert tenant is not None
    return tenant


def _handoff_to_mode_b(session: Session, run: Run, tenant: Tenant) -> bool:
    """Queue this run's Mode B half. If queueing fails (a Redis blip), finalize
    now with what Mode A collected instead of stranding committed results
    unprocessed. Returns True when Mode B was queued (it will finalize)."""
    assert run.id is not None
    try:
        enqueue_run_mode_b(run.id)
        return True
    except Exception as exc:  # noqa: BLE001
        note = f"could not queue the browser engines: {type(exc).__name__}"
        run.error = (run.error or note)[:500]
        session.add(run)
        session.commit()
        _finalize_run(session, run, tenant)
        return False


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


# (persona_id, persona_name, persona_prompt, persona_segment)
_PersonaTuple = tuple[int | None, str, str, str]
# (query_id, query_text, persona_runs)
_QueryTuple = tuple[int | None, str, list[dict]]

_GENERIC_SEGMENT = "generic"


def _persona_cell(persona: _PersonaTuple, overlay: str = "") -> _PersonaTuple:
    """A persona snapshot with an optional vertical-overlay clause appended to
    its preamble; the name is annotated so overlay runs are distinguishable in
    the results view while still rolling up under the base segment."""
    pid, pname, pprompt, pseg = persona
    if not overlay:
        return persona
    prompt = f"{pprompt} {overlay}".strip()
    return (pid, f"{pname} ({overlay})", prompt, pseg)


def _baseline_persona(personas: list[_PersonaTuple]) -> _PersonaTuple | None:
    """The baseline persona used for the diagnosis twin and natural probe: the
    'generic' persona when the tenant has one (selective mode), else the first
    persona (legacy)."""
    for p in personas:
        if p[3] == _GENERIC_SEGMENT:
            return p
    return personas[0] if personas else None


def matrix_cells(
    queries: list[_QueryTuple],
    personas: list[_PersonaTuple],
    *,
    first_persona_only: bool = False,
) -> list[tuple[int | None, str, _PersonaTuple]]:
    """The (query_id, query_text, persona) cells to run for the client-facing
    matrix. Pure — unit-tested without a DB.

    Selective mode (the tenant has a 'generic' persona): every query runs the
    generic baseline PLUS the personas named in its persona_runs, each with its
    optional vertical overlay. This is the curated query×persona matrix.

    Legacy mode (no 'generic' persona): the full persona × query cross-product,
    or the first persona only when first_persona_only=True (Mode B) — the exact
    pre-matrix behaviour, so existing tenants are unaffected."""
    if not personas:
        return []
    by_segment: dict[str, _PersonaTuple] = {}
    for p in personas:
        by_segment.setdefault(p[3], p)
    generic = [p for p in personas if p[3] == _GENERIC_SEGMENT]

    if not generic:
        pool = personas[:1] if first_persona_only else personas
        return [(qid, qtext, p) for (qid, qtext, _runs) in queries for p in pool]

    cells: list[tuple[int | None, str, _PersonaTuple]] = []
    for qid, qtext, runs in queries:
        for g in generic:
            cells.append((qid, qtext, g))
        for run in runs or []:
            seg = run.get("segment")
            if not seg or seg == _GENERIC_SEGMENT:
                continue
            base = by_segment.get(seg)
            if base is None:  # unknown segment in config — skip, don't crash
                continue
            cells.append((qid, qtext, _persona_cell(base, run.get("overlay", ""))))
    return cells


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
    # `spent` = actual cost of returned calls; `reserved` = conservative
    # estimate held for in-flight calls. Reserving BEFORE dispatch (§audit H6)
    # closes the race where up to `concurrency` calls all pass a check that
    # only reads post-call `spent` — which let the cap be silently overshot.
    state = {"spent": 0.0, "reserved": 0.0, "capped": False}

    async def one(item: _AWorkItem) -> dict[str, Any] | None:
        adapter = A_ADAPTERS[item.surface]
        model = model_for(item.surface, model_tier, getattr(settings, adapter.model_attr))
        # Conservative upper-bound estimate for the reservation (over-reserving
        # withholds slightly early — the safe direction for a spend cap).
        est = adapter.cost_fn(model, _EST_INPUT_TOKENS, _EST_OUTPUT_TOKENS, _EST_SEARCH_CALLS)
        async with semaphore:
            async with lock:
                if month_spent_before + state["spent"] + state["reserved"] + est > cap_usd:
                    state["capped"] = True
                    return None
                state["reserved"] += est
            try:
                outcome = await adapter.module.retrieve(
                    item.persona_prompt,
                    item.query_text,
                    api_key=getattr(settings, adapter.key_attr),
                    model=model,
                    timeout_s=getattr(settings, adapter.timeout_attr),
                    # Search, natural and shard probes all search; only the
                    # diagnosis twin runs with retrieval disabled.
                    web_search=item.variant != ResultVariant.nosearch,
                    # M2 natural probe: offer the tool but don't force it.
                    force_search=item.variant != ResultVariant.natural,
                )
            except Exception as exc:  # noqa: BLE001 — a failed call is data, not a crash
                async with lock:
                    state["reserved"] -= est
                return {"item": item, "model": model, "error": f"{type(exc).__name__}: {exc}"[:500]}
            cost = adapter.cost_fn(
                outcome.parsed.model or model,
                outcome.parsed.input_tokens,
                outcome.parsed.output_tokens,
                outcome.parsed.web_search_calls,
            )
            async with lock:
                state["reserved"] -= est
                state["spent"] += cost
            return {"item": item, "outcome": outcome, "cost": cost, "model": model}

    results = await asyncio.gather(*[one(item) for item in work])
    # Belt-and-suspenders: if an estimate under-shot actual token use enough to
    # cross the cap, still surface the run as capped.
    capped = state["capped"] or (month_spent_before + state["spent"] > cap_usd)
    return list(results), capped


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
            (q.id, q.text, list(q.persona_runs or []))
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
        cached_twins: dict[tuple[str, str], tuple[str, str, Any]] = {}
        if personas and limits.diagnosis and settings.diagnosis_refresh_days > 0:
            cutoff = utcnow() - timedelta(days=settings.diagnosis_refresh_days)
            query_texts = {qtext for (_qid, qtext, _runs) in queries}
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
                    # Carry the ORIGINAL capture's timestamp (§audit worker-5).
                    # Cloning with a fresh created_at would keep the twin
                    # perpetually "fresh", so it would be re-cloned every run and
                    # the TTL would never age it out.
                    cached_twins[key] = (r.raw_uri, r.response_hash, created)

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
            run.error = f"No Mode A surface is configured on this deployment. Set: {needed}"
            run.counts = {
                "planned": 0, "completed": 0, "failed": 0, "withheld_by_cap": 0,
                **{f"unconfigured:{s}": 1 for s in unconfigured},
            }
            if _b_surfaces(run):
                # The browser/SERP surfaces don't need these keys — still run
                # them rather than losing the whole run to one missing key.
                session.add(run)
                session.commit()
                _handoff_to_mode_b(session, run, tenant_for_handoff(session, run))
                return
            run.status = RunStatus.failed
            run.finished_at = utcnow()
            session.add(run)
            session.commit()
        return

    # The client-facing matrix (selective query×persona, or full cross-product
    # for tenants without a 'generic' baseline), plus one search-disabled twin
    # per (query, surface) on the baseline persona — the dual-query diff the
    # classifier consumes (§6.1). The twin applies to every provider with a
    # search-disabled mode (all four since Perplexity's Agent API migration).
    # Plain snapshots: no DB
    # connection during dispatch.
    cells = matrix_cells(queries, personas)
    work: list[_AWorkItem] = [
        _AWorkItem(qid, qtext, pid, pname, pprompt, pseg, s, ResultVariant.search)
        for s in configured
        for (qid, qtext, (pid, pname, pprompt, pseg)) in cells
    ]
    baseline = _baseline_persona(personas)
    if baseline is not None and limits.diagnosis:
        bpid, bpname, bpprompt, bpseg = baseline
        work += [
            _AWorkItem(qid, qtext, bpid, bpname, bpprompt, bpseg, s, ResultVariant.nosearch)
            for s in configured
            if A_ADAPTERS[s].supports_nosearch
            for (qid, qtext, _runs) in queries
            if (qtext, s) not in cached_twins  # twin still fresh — reuse below
        ]

    # M2 natural routing probe: an un-forced call on a deterministic fraction of
    # queries, for the surfaces that force search (only those hide routing).
    # Baseline persona only; measurement-only, excluded from scoring.
    probe_frac = getattr(settings, "natural_probe_fraction", 0.0)
    forced_surfaces = [s for s in configured if A_ADAPTERS[s].forces_search]
    if baseline is not None and probe_frac > 0 and forced_surfaces and queries:
        n_probe = max(1, round(probe_frac * len(queries)))
        probe_queries = queries[:n_probe]
        bpid, bpname, bpprompt, bpseg = baseline
        work += [
            _AWorkItem(qid, qtext, bpid, bpname, bpprompt, bpseg, s, ResultVariant.natural)
            for s in forced_surfaces
            for (qid, qtext, _runs) in probe_queries
        ]

    counts = {"planned": len(work), "completed": 0, "failed": 0, "withheld_by_cap": 0}
    if unconfigured:
        counts["skipped_unconfigured"] = len(unconfigured)
        # Per-surface flags so the admin readiness panel can name the engine
        # whose key is missing.
        for s in unconfigured:
            counts[f"unconfigured:{s}"] = 1
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
        baseline_twin = _baseline_persona(personas)
        if cached_twins and baseline_twin is not None:
            qid_by_text = {qtext: qid for (qid, qtext, _runs) in queries}
            bpid0, bpname0, _bpprompt0, bpseg0 = baseline_twin
            cloned = 0
            for (qtext, twin_surface), (uri, rhash, created_ts) in cached_twins.items():
                if twin_surface not in configured:
                    continue
                session.add(
                    Result(
                        run_id=run_id,
                        tenant_id=run.tenant_id,
                        query_id=qid_by_text.get(qtext),
                        persona_id=bpid0,
                        query_text=qtext,
                        persona_name=bpname0,
                        persona_segment=bpseg0,
                        surface=SurfaceCode(twin_surface),
                        variant=ResultVariant.nosearch,
                        raw_uri=uri,
                        response_hash=rhash,
                        latency_ms=0,
                        # Inherit the source capture's age so the TTL cutoff can
                        # eventually expire it (§audit worker-5).
                        created_at=created_ts,
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

        if _b_surfaces(run) and _handoff_to_mode_b(session, run, tenant):
            # Mode B runs on the Playwright container and finalizes the run
            # (single finalize + processing pass, no cross-worker races).
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
        # Guard legacy rows: M6 backfilled aio_geo NULL on pre-existing tenants
        # (no server_default), and default_factory fires only on construction,
        # not on load — so a migrated row can load None here.
        aio_geo = dict(tenant.aio_geo or {"gl": "ca", "hl": "en"})
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
        # Same set, order and plan limits as Mode A, so both halves of a run
        # measure the same prompts and personas (and B can't exceed the plan).
        queries = [
            (q.id, q.text, list(q.persona_runs or []))
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
        base_counts = dict(run.counts) if run.counts else {}
        if not settings.serpapi_key and str(SurfaceCode.google_ai_mode) in b_surfaces:
            # AI Mode only runs through SerpApi: skip it as unconfigured (the
            # readiness panel says what to set) instead of N failed calls.
            b_surfaces = [b for b in b_surfaces if b != str(SurfaceCode.google_ai_mode)]
            base_counts[f"unconfigured:{SurfaceCode.google_ai_mode}"] = 1

    # Work fans out over locations × queries × surfaces (§SCRAPING_V3 Part 2).
    # google_aio is per (query, geo) — a SERP takes no persona (§6.3).
    # Persona-framed web surfaces run the selective query×persona matrix (or the
    # first persona only for tenants without a 'generic' baseline — the
    # pre-matrix DECISIONS M4.1 behaviour).
    web_cells = matrix_cells(queries, personas, first_persona_only=True)
    work: list[_BWorkItem] = []
    for surface in b_surfaces:
        if surface in (str(SurfaceCode.google_aio), str(SurfaceCode.google_ai_mode)):
            work += [
                _BWorkItem(qid, qtext, None, "(serp)", "", "", surface, label, geo)
                for (label, geo) in locations
                for (qid, qtext, _runs) in queries
            ]
        else:
            work += [
                _BWorkItem(qid, qtext, pid, pname, pprompt, pseg, surface, label, geo)
                for (label, geo) in locations
                for (qid, qtext, (pid, pname, pprompt, pseg)) in web_cells
            ]

    base_env = _base_scrape_env(settings)

    counts = dict(base_counts)
    counts["planned"] = counts.get("planned", 0) + len(work)
    mode_b_cost = 0.0
    booked_b_cost = 0.0  # portion of mode_b_cost already added to run.cost_usd
    capped = False

    # Circuit breaker: a surface that fails N times in a row (browser won't
    # launch, proxy dead, wall on every page) has its remaining items recorded
    # as skipped instead of burning a scrape + rate-limit sleep each — without
    # it one broken engine holds the only worker for hours.
    consecutive_fail: dict[str, int] = {}
    last_error: dict[str, str] = {}
    last_call_at: dict[str, float] = {}
    loop = asyncio.get_running_loop()

    for index, wi in enumerate(work):
        if consecutive_fail.get(wi.surface, 0) >= _B_BREAKER_THRESHOLD:
            with Session(get_engine()) as session:
                session.add(Result(
                    run_id=run_id, tenant_id=tenant_id, query_id=wi.query_id,
                    persona_id=wi.persona_id, query_text=wi.query_text,
                    persona_name=wi.persona_name, persona_segment=wi.persona_segment,
                    surface=SurfaceCode(wi.surface), mode=RunMode.B,
                    location_label=wi.location_label, status=ResultStatus.error,
                    error=(f"skipped: {wi.surface} failed {_B_BREAKER_THRESHOLD} times in a "
                           f"row (last: {last_error.get(wi.surface, '')})")[:500],
                ))
                counts["failed"] = counts.get("failed", 0) + 1
                counts[f"skipped:{wi.surface}"] = counts.get(f"skipped:{wi.surface}", 0) + 1
                run = session.get(Run, run_id)
                if run is not None:
                    run.counts = counts
                    session.add(run)
                session.commit()
            continue
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
        # A SerpApi AIO capture may need a second (page_token) search; leave
        # room for it so the cap is never crossed.
        headroom = (
            settings.serpapi_cost_per_search
            if wi.surface == str(SurfaceCode.google_aio)
            and settings.google_aio_provider == "serpapi"
            else 0.0
        )
        if month_spent_before + mode_b_cost + call_cost + headroom > cap_usd:
            capped = True
            counts["withheld_by_cap"] = counts.get("withheld_by_cap", 0) + (len(work) - index)
            break
        mode_b_cost += call_cost

        adapter_module, model_label, rate_attr, timeout_attr = B_ADAPTERS[wi.surface]
        # Pace per surface: only wait out the remainder of THIS engine's
        # interval, not a full sleep between two different engines.
        rate = max(float(getattr(settings, rate_attr)), 0.1)
        if wi.surface in last_call_at:
            wait = 60.0 / rate - (loop.time() - last_call_at[wi.surface])
            if wait > 0:
                await asyncio.sleep(wait)
        last_call_at[wi.surface] = loop.time()
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
                # Hard ceiling over the adapter's own step timeouts, so one hung
                # page can't consume the whole job's time budget.
                outcome = await asyncio.wait_for(
                    google_aio.capture(
                        wi.query_text,
                        geo=wi.geo or aio_geo,
                        provider=settings.google_aio_provider,
                        serpapi_key=settings.serpapi_key,
                        headless=settings.chatgpt_web_headless,
                        timeout_s=settings.google_aio_timeout_s,
                        executable_path=settings.playwright_chromium_path or None,
                        env=env,
                    ),
                    timeout=settings.google_aio_timeout_s + _B_TIMEOUT_GRACE_S,
                )
                parsed_text = outcome.aio_text
                if outcome.extra_searches:
                    extra_cost = outcome.extra_searches * settings.serpapi_cost_per_search
                    call_cost += extra_cost
                    mode_b_cost += extra_cost
                response_payload = {
                    "aio_summary": asdict(outcome.summary),
                    "aio_html": outcome.aio_html,
                    # §6.3: the full rendered SERP goes to object storage.
                    "page_html": outcome.page_html,
                }
            elif wi.surface == str(SurfaceCode.google_ai_mode):
                ai_mode = await asyncio.wait_for(
                    google_ai_mode.capture(
                        wi.query_text,
                        geo=wi.geo or aio_geo,
                        api_key=settings.serpapi_key,
                        timeout_s=settings.google_ai_mode_timeout_s,
                    ),
                    timeout=settings.google_ai_mode_timeout_s + _B_TIMEOUT_GRACE_S,
                )
                outcome = ai_mode
                parsed_text = ai_mode.text
                response_payload = {"shopping_results": ai_mode.shopping_results}
            else:
                timeout_s = float(getattr(settings, timeout_attr))
                outcome = await asyncio.wait_for(
                    adapter_module.retrieve(
                        wi.persona_prompt,
                        wi.query_text,
                        headless=settings.chatgpt_web_headless,
                        timeout_s=timeout_s,
                        executable_path=settings.playwright_chromium_path or None,
                        env=env,
                    ),
                    timeout=timeout_s + _B_TIMEOUT_GRACE_S,
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
            if blocked or error is not None or outcome is None:
                consecutive_fail[wi.surface] = consecutive_fail.get(wi.surface, 0) + 1
                last_error[wi.surface] = (error or "no outcome")[:200]
            else:
                consecutive_fail[wi.surface] = 0
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
                # Book this call's spend now, not only at the end: a crash or
                # job timeout mid-run must not hide spend from the monthly cap.
                run.cost_usd = round((run.cost_usd or 0.0) + (mode_b_cost - booked_b_cost), 6)
                booked_b_cost = mode_b_cost
                counts["mode_b_cost_usd"] = round(mode_b_cost, 6)
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
        # Book any Mode B spend not yet added per call (Mode A's is already in).
        run.cost_usd = round((run.cost_usd or 0.0) + (mode_b_cost - booked_b_cost), 6)
        session.add(run)
        session.commit()
        _finalize_run(session, run, tenant)


def run_fanout_reprobe(run_id: int) -> None:
    """Fan-out re-probe job (§FANOUT_SCORECARD M25b), enqueued by _finalize_run.
    A crash is flagged in the run's counts; the run's own status is already
    final and is left alone."""
    try:
        asyncio.run(_run_fanout_reprobe(run_id))
    except Exception:  # noqa: BLE001
        with Session(get_engine()) as session:
            run = session.get(Run, run_id)
            if run is not None:
                run.counts = {**run.counts, "fanout_reprobe_crashed": 1}
                session.add(run)
                session.commit()
        raise


def _mark_shards(session: Session, ids: list[int], status: str) -> None:
    for shard_id in ids:
        shard = session.get(FanoutShard, shard_id)
        if shard is not None:
            shard.probe_status = status
            session.add(shard)


async def _run_fanout_reprobe(run_id: int) -> None:
    """Re-run the top unresolved shards as their own queries on an engine that
    issued them, and record honest per-shard presence. Top-K per prompt and a
    per-run ceiling from the plan, then the monthly spend cap per call — every
    shard left out is stamped with why (dropped_k / dropped_ceiling /
    withheld_cap), never silently skipped (§4, §8)."""
    settings = get_settings()

    # Phase 1 — load, rank, and choose. Then RELEASE the connection.
    with Session(get_engine()) as session:
        run = session.get(Run, run_id)
        if run is None or run.status != RunStatus.complete:
            return
        tenant = session.get(Tenant, run.tenant_id)
        assert tenant is not None
        limits = limits_for(tenant.plan)
        if not tenant.fanout_reprobe_enabled or limits.shard_probes_per_run <= 0:
            return
        tenant_id = run.tenant_id
        tenant_slug = tenant.slug
        cap_usd = tenant.monthly_spend_cap_usd

        brand = session.exec(
            select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
        ).first()
        brand_name = brand.brand_name if brand else tenant.name
        brand_aliases = list(brand.aliases) if brand else []
        brand_domains = list(brand.domains) if brand else []
        competitors = [
            (c.id, c.name, list(c.aliases), list(c.domains))
            for c in session.exec(
                select(Competitor).where(Competitor.tenant_id == tenant_id)
            ).all()
        ]
        comp_tokens = {
            t.lower() for _cid, name, aliases, _d in competitors for t in [name, *aliases] if t
        }
        brand_tokens = {t.lower() for t in [brand_name, *brand_aliases] if t}

        # Parent-prompt loss signals from this run's own answers.
        search = [
            r for r in session.exec(select(Result).where(Result.run_id == run_id)).all()
            if r.variant == ResultVariant.search and r.status == ResultStatus.ok
        ]
        parent_of = {r.id: r.query_text for r in search if r.id is not None}
        brand_named: set[str] = set()
        rival_named: set[str] = set()
        if parent_of:
            for m in session.exec(
                select(Mention).where(Mention.result_id.in_(list(parent_of)))  # pyright: ignore[reportAttributeAccessIssue]
            ).all():
                (brand_named if m.entity_type == "brand" else rival_named).add(
                    parent_of[m.result_id]
                )

        configured = {
            s for s in A_ADAPTERS if getattr(settings, A_ADAPTERS[s].key_attr)
        }
        shards = list(
            session.exec(
                select(FanoutShard).where(
                    FanoutShard.run_id == run_id, FanoutShard.source == "unresolved"
                )
            ).all()
        )
        surface_of: dict[int, str] = {}
        candidates: list[ShardCandidate] = []
        for shard in shards:
            assert shard.id is not None
            surface = probe_surface_for(list(shard.issuing_surfaces or []), configured)
            if surface is None:
                continue  # no issuing engine we can call — stays unresolved
            surface_of[shard.id] = surface
            low = shard.shard_text.lower()
            candidates.append(
                ShardCandidate(
                    shard_id=shard.id,
                    parent=shard.parent_query_text,
                    text=shard.shard_text,
                    reach=shard.reach,
                    parent_brand_absent=shard.parent_query_text not in brand_named,
                    shard_names_rival=names_present(low, comp_tokens),
                    parent_names_rival=shard.parent_query_text in rival_named,
                    names_brand=names_present(low, brand_tokens),
                )
            )
        chosen, dropped_k, dropped_ceiling = select_candidates(
            candidates, limits.shard_probes_per_prompt, limits.shard_probes_per_run
        )
        _mark_shards(session, [c.shard_id for c in dropped_k], "dropped_k")
        _mark_shards(session, [c.shard_id for c in dropped_ceiling], "dropped_ceiling")

        personas = [
            (p.id, p.name, p.prompt_text, p.segment_tag)
            for p in session.exec(
                select(Persona).where(Persona.tenant_id == tenant_id).order_by(Persona.id)  # pyright: ignore[reportArgumentType]
            ).all()
        ]
        baseline = _baseline_persona(personas) or (
            None, "(shard)", "You are a helpful assistant.", ""
        )
        month_spent_before = month_spend_usd(session, tenant_id)
        session.commit()

    bpid, bpname, bpprompt, bpseg = baseline
    work = [
        _AWorkItem(None, c.text, bpid, bpname, bpprompt, bpseg,
                   surface_of[c.shard_id], ResultVariant.shard)
        for c in chosen
    ]

    # Phase 2 — dispatch. NO DB CONNECTION HELD. Same cap reservation as a run.
    outcomes, capped = await _dispatch_all(
        work,
        settings=settings,
        model_tier=limits.model_tier,
        concurrency=settings.openai_concurrency,
        month_spent_before=month_spent_before,
        cap_usd=cap_usd,
    )

    # Phase 3 — persist the probes and resolve the shards.
    counts = {
        "fanout_reprobed": 0,
        "fanout_reprobe_failed": 0,
        "fanout_withheld_by_cap": 0,
        "fanout_dropped_k": len(dropped_k),
        "fanout_dropped_ceiling": len(dropped_ceiling),
    }
    cost = 0.0
    with Session(get_engine()) as session:
        run = session.get(Run, run_id)
        assert run is not None
        for index, (cand, item) in enumerate(zip(chosen, outcomes, strict=True)):
            shard = session.get(FanoutShard, cand.shard_id)
            if shard is None:
                continue
            if item is None:
                counts["fanout_withheld_by_cap"] += 1
                shard.probe_status = "withheld_cap"
                session.add(shard)
                continue
            wi: _AWorkItem = item["item"]
            result = Result(
                run_id=run_id,
                tenant_id=tenant_id,
                persona_id=wi.persona_id,
                query_text=wi.query_text,
                persona_name=wi.persona_name,
                persona_segment=wi.persona_segment,
                surface=SurfaceCode(wi.surface),
                variant=ResultVariant.shard,
            )
            shard.probe_surface = wi.surface
            if "error" in item:
                counts["fanout_reprobe_failed"] += 1
                result.status = ResultStatus.error
                result.error = item["error"]
                session.add(result)
                shard.probe_status = "error"
                session.add(shard)
                continue
            outcome = item["outcome"]
            cost += item["cost"]
            counts["fanout_reprobed"] += 1
            cited = [c.domain for c in outcome.parsed.citations]
            result.latency_ms = outcome.latency_ms
            result.web_search_calls = outcome.parsed.web_search_calls
            result.fanout_queries = list(outcome.parsed.fanout_queries)
            result.response_hash = hashlib.sha256(
                outcome.parsed.text.encode("utf-8")
            ).hexdigest()
            # No Citation/Mention rows for a shard probe: presence lives on the
            # FanoutShard, so no citation or mention read can ever count it.
            result.raw_uri = write_raw_envelope(
                tenant_slug,
                run_id,
                f"shard-{index:04d}",
                {
                    "surface": wi.surface,
                    "mode": "A",
                    "variant": "shard",
                    "query": wi.query_text,
                    "parent_query": cand.parent,
                    "persona": wi.persona_name,
                    "persona_prompt": wi.persona_prompt,
                    "model": item.get("model", ""),
                    "response": outcome.payload,
                    "parsed_text": outcome.parsed.text,
                    "citations": [
                        {"url": c.url, "domain": c.domain} for c in outcome.parsed.citations
                    ],
                    "cost_usd": item["cost"],
                },
                session=session,
            )
            session.add(result)
            session.flush()
            present, winners = evaluate_probe(
                outcome.parsed.text,
                cited,
                brand_name=brand_name,
                brand_aliases=brand_aliases,
                brand_domains=brand_domains,
                competitors=competitors,
            )
            shard.brand_present = present
            shard.winners = winners
            shard.source = "reprobed"
            shard.probe_status = "ok"
            shard.probe_result_id = result.id
            shard.probed_at = utcnow()
            shard.priority = shard_priority(present, winners)
            session.add(shard)

        counts["fanout_reprobe_cost_usd"] = round(cost, 6)  # pyright: ignore[reportArgumentType]
        if capped:
            counts["fanout_reprobe_capped"] = 1
        run.counts = {**run.counts, **counts}
        # Probe spend accrues to the run, so the monthly cap sees it.
        run.cost_usd = round((run.cost_usd or 0.0) + cost, 6)
        session.add(run)
        session.commit()
