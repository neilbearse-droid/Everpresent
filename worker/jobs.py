"""RQ job functions. Mode A dispatch lives here: the engine stays pure
retrieval/parsing/cost, the API layer stays request-shaped, and this is the
only place the two meet a database session and a provider key."""

import asyncio
import hashlib
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
    RunStatus,
    SurfaceCode,
    Tenant,
    utcnow,
)
from api.processing_service import process_run
from api.runs_service import month_spend_usd
from api.storage import write_raw_envelope
from engine.costs import estimate_openai_cost_usd
from engine.retrievers import openai_api


def ping() -> str:
    return "pong"


def run_mode_a(run_id: int) -> None:
    asyncio.run(_run_mode_a(run_id))


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
        work = [
            (q, p, s, ResultVariant.search)
            for s in run.surface_set
            for q in queries
            for p in personas
        ]
        if personas:
            work += [
                (q, personas[0], s, ResultVariant.nosearch)
                for s in run.surface_set
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
        run.counts = counts
        run.cost_usd = round(total_cost, 6)
        run.finished_at = utcnow()
        if capped:
            run.status = RunStatus.capped
            run.error = (
                f"monthly spend cap reached (cap ${tenant.monthly_spend_cap_usd:.2f}, "
                f"spent ${month_spent_before:.2f} before this run)"
            )
        elif counts["completed"] == 0 and counts["failed"] > 0:
            run.status = RunStatus.failed
            run.error = "all calls failed; see per-result errors"
        else:
            run.status = RunStatus.complete
        session.add(run)
        session.commit()

        # Processing (§6.4): mentions, citation categories, classification,
        # visibility rollup. A processing failure must not lose the run's
        # stored results — record it on the run instead.
        if counts["completed"] > 0:
            try:
                processing_counts = process_run(session, run)
                run.counts = {**run.counts, **processing_counts}
            except Exception as exc:  # noqa: BLE001
                run.error = f"processing failed: {type(exc).__name__}: {exc}"[:500]
            session.add(run)
            session.commit()
