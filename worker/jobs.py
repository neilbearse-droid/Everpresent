"""RQ job functions. Mode A dispatch lives here: the engine stays pure
retrieval/parsing/cost, the API layer stays request-shaped, and this is the
only place the two meet a database session and a provider key."""

import asyncio
import hashlib
from dataclasses import asdict
from typing import Any

from sqlmodel import Session, select

from api.config import get_settings
from api.db import get_engine
from api.models import (
    Citation,
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
from api.processing_service import process_run
from api.queue import enqueue_run_mode_b
from api.runs_service import MODE_A_SURFACES, MODE_B_SURFACES, month_spend_usd
from api.storage import write_raw_envelope
from engine.costs import estimate_openai_cost_usd
from engine.retrievers import chatgpt_web, google_aio, openai_api, perplexity_web


def ping() -> str:
    return "pong"


def run_mode_a(run_id: int) -> None:
    asyncio.run(_run_mode_a(run_id))


def run_mode_b(run_id: int) -> None:
    asyncio.run(_run_mode_b(run_id))


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
    elif counts.get("completed", 0) == 0 and counts.get("failed", 0) > 0:
        run.status = RunStatus.failed
        run.error = run.error or "all calls failed; see per-result errors"
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


async def _dispatch_all(
    work: list[tuple[Query, Persona, str, ResultVariant]],
    *,
    api_key: str,
    model: str,
    timeout_s: float,
    concurrency: int,
    month_spent_before: float,
    cap_usd: float,
) -> tuple[list[dict[str, Any] | None], bool]:
    """Runs the (query × persona × surface) matrix with a concurrency limit.
    The spend cap is checked BEFORE each dispatch (§6.1/§9); a None slot means
    the call was withheld by the cap. Actual per-call cost is only known after
    the call returns, so a burst of in-flight calls can overshoot the cap by
    at most `concurrency` calls — accepted and documented."""
    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    state = {"cost": 0.0, "capped": False}

    async def one(
        query: Query, persona: Persona, surface: str, variant: ResultVariant
    ) -> dict[str, Any] | None:
        async with semaphore:
            async with lock:
                if month_spent_before + state["cost"] >= cap_usd:
                    state["capped"] = True
                    return None
            base = {
                "query": query,
                "persona": persona,
                "surface": surface,
                "variant": variant,
            }
            try:
                outcome = await openai_api.retrieve(
                    persona.prompt_text,
                    query.text,
                    api_key=api_key,
                    model=model,
                    timeout_s=timeout_s,
                    web_search=variant == ResultVariant.search,
                )
            except Exception as exc:  # noqa: BLE001 — a failed call is data, not a crash
                return {**base, "error": f"{type(exc).__name__}: {exc}"[:500]}
            cost = estimate_openai_cost_usd(
                outcome.parsed.model or model,
                outcome.parsed.input_tokens,
                outcome.parsed.output_tokens,
                outcome.parsed.web_search_calls,
            )
            async with lock:
                state["cost"] += cost
            return {**base, "outcome": outcome, "cost": cost}

    results = await asyncio.gather(*[one(q, p, s, v) for q, p, s, v in work])
    return list(results), state["capped"]


async def _run_mode_a(run_id: int) -> None:
    settings = get_settings()
    with Session(get_engine()) as session:
        run = session.get(Run, run_id)
        if run is None or run.status != RunStatus.pending:
            return
        tenant = session.get(Tenant, run.tenant_id)
        assert tenant is not None

        run.status = RunStatus.running
        run.started_at = utcnow()
        session.add(run)
        session.commit()

        queries = list(
            session.exec(
                select(Query).where(Query.tenant_id == tenant.id, Query.active == True)  # noqa: E712
            ).all()
        )
        personas = list(
            session.exec(select(Persona).where(Persona.tenant_id == tenant.id)).all()
        )
        # The client-facing matrix, plus one search-disabled twin per
        # (query, surface) on the first persona — the dual-query diff the
        # classifier consumes (§6.1).
        a_surfaces = _a_surfaces(run)
        work = [
            (q, p, s, ResultVariant.search)
            for s in a_surfaces
            for q in queries
            for p in personas
        ]
        if personas:
            work += [
                (q, personas[0], s, ResultVariant.nosearch)
                for s in a_surfaces
                for q in queries
            ]

        counts = {"planned": len(work), "completed": 0, "failed": 0, "withheld_by_cap": 0}

        if not settings.openai_api_key:
            run.status = RunStatus.failed
            run.error = "OPENAI_API_KEY is not configured on this deployment"
            run.counts = counts
            run.finished_at = utcnow()
            session.add(run)
            session.commit()
            return

        month_spent_before = month_spend_usd(session, run.tenant_id)
        outcomes, capped = await _dispatch_all(
            work,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout_s=settings.openai_timeout_s,
            concurrency=settings.openai_concurrency,
            month_spent_before=month_spent_before,
            cap_usd=tenant.monthly_spend_cap_usd,
        )

        total_cost = 0.0
        citation_count = 0
        for index, item in enumerate(outcomes):
            if item is None:
                counts["withheld_by_cap"] += 1
                continue
            query: Query = item["query"]
            persona: Persona = item["persona"]
            result = Result(
                run_id=run_id,
                tenant_id=run.tenant_id,
                query_id=query.id,
                persona_id=persona.id,
                query_text=query.text,
                persona_name=persona.name,
                persona_segment=persona.segment_tag,
                surface=SurfaceCode(item["surface"]),
                variant=item["variant"],
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
                result.response_hash = hashlib.sha256(
                    outcome.parsed.text.encode("utf-8")
                ).hexdigest()
                result.raw_uri = write_raw_envelope(
                    tenant.slug,
                    run_id,
                    f"result-{index:04d}",
                    {
                        "surface": item["surface"],
                        "mode": "A",
                        "variant": item["variant"],
                        "query": query.text,
                        "persona": persona.name,
                        "persona_prompt": persona.prompt_text,
                        "model": settings.openai_model,
                        "response": outcome.payload,
                        "parsed_text": outcome.parsed.text,
                        "cost_usd": item["cost"],
                    },
                )
            session.add(result)
            session.flush()
            if "error" not in item and item["variant"] == ResultVariant.search:
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
                        )
                    )

        counts["citations"] = citation_count
        if capped:
            counts["capped"] = True
            run.error = (
                f"monthly spend cap reached (cap ${tenant.monthly_spend_cap_usd:.2f}, "
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
    with Session(get_engine()) as session:
        run = session.get(Run, run_id)
        if run is None or run.status not in (RunStatus.pending, RunStatus.running):
            return
        tenant = session.get(Tenant, run.tenant_id)
        assert tenant is not None
        if run.status == RunStatus.pending:  # B-only run, not chained from A
            run.status = RunStatus.running
            run.started_at = utcnow()
            session.add(run)
            session.commit()

        queries = list(
            session.exec(
                select(Query).where(Query.tenant_id == tenant.id, Query.active == True)  # noqa: E712
            ).all()
        )
        personas = list(session.exec(select(Persona).where(Persona.tenant_id == tenant.id)).all())
        # google_aio is per (query, geo) — a SERP takes no persona (§6.3);
        # persona-framed web surfaces use the first persona (DECISIONS M4.1).
        work: list[tuple[Query, Persona | None, str]] = []
        for surface in _b_surfaces(run):
            if surface == str(SurfaceCode.google_aio):
                work += [(q, None, surface) for q in queries]
            elif personas:
                work += [(q, personas[0], surface) for q in queries]

        counts = dict(run.counts) if run.counts else {}
        counts["planned"] = counts.get("planned", 0) + len(work)

        for index, (query, persona, surface) in enumerate(work):
            adapter_module, model_label, rate_attr = B_ADAPTERS[surface]
            if index > 0:
                rate = max(float(getattr(settings, rate_attr)), 0.1)
                await asyncio.sleep(60.0 / rate)
            is_aio = surface == str(SurfaceCode.google_aio)
            result = Result(
                run_id=run_id,
                tenant_id=run.tenant_id,
                query_id=query.id,
                persona_id=persona.id if persona else None,
                query_text=query.text,
                persona_name=persona.name if persona else "(serp)",
                persona_segment=persona.segment_tag if persona else "",
                surface=SurfaceCode(surface),
                mode=RunMode.B,
            )
            try:
                if is_aio:
                    outcome = await google_aio.capture(
                        query.text,
                        geo=tenant.aio_geo,
                        provider=settings.google_aio_provider,
                        serpapi_key=settings.serpapi_key,
                        headless=settings.chatgpt_web_headless,
                        timeout_s=settings.google_aio_timeout_s,
                        executable_path=settings.playwright_chromium_path or None,
                    )
                    parsed_text = outcome.aio_text
                    response_payload: dict[str, Any] = {
                        "aio_summary": asdict(outcome.summary),
                        "aio_html": outcome.aio_html,
                        # §6.3: the full rendered SERP goes to object storage.
                        "page_html": outcome.page_html,
                    }
                else:
                    assert persona is not None
                    outcome = await adapter_module.retrieve(
                        persona.prompt_text,
                        query.text,
                        headless=settings.chatgpt_web_headless,
                        timeout_s=settings.chatgpt_web_timeout_s,
                        executable_path=settings.playwright_chromium_path or None,
                    )
                    parsed_text = outcome.text
                    response_payload = {"html": outcome.html_fragment}
            except Exception as exc:  # noqa: BLE001 — a failed scrape is data
                counts["failed"] = counts.get("failed", 0) + 1
                result.status = ResultStatus.error
                result.error = f"{type(exc).__name__}: {exc}"[:500]
                session.add(result)
                session.commit()
                continue

            counts["completed"] = counts.get("completed", 0) + 1
            result.latency_ms = outcome.latency_ms
            result.response_hash = hashlib.sha256(parsed_text.encode("utf-8")).hexdigest()
            result.raw_uri = write_raw_envelope(
                tenant.slug,
                run_id,
                f"result-b-{index:04d}",
                {
                    "surface": surface,
                    "mode": "B",
                    "variant": "search",
                    "query": query.text,
                    "persona": result.persona_name,
                    "persona_prompt": persona.prompt_text if persona else "",
                    "model": model_label,
                    "adapter_version": adapter_module.ADAPTER_VERSION,
                    "response": response_payload,
                    "parsed_text": parsed_text,
                    "cost_usd": 0.0,
                },
            )
            session.add(result)
            session.flush()
            assert result.id is not None
            for citation in outcome.citations:
                counts["citations"] = counts.get("citations", 0) + 1
                session.add(
                    Citation(
                        result_id=result.id,
                        tenant_id=run.tenant_id,
                        url=citation.url,
                        domain=citation.domain,
                    )
                )
            session.commit()

        run.counts = counts
        session.add(run)
        session.commit()
        _finalize_run(session, run, tenant)
