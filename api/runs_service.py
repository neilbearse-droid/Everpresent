"""Run lifecycle shared by the admin trigger routes and the read endpoints.
Dispatch itself lives in worker/jobs.py."""

from datetime import UTC, datetime

from sqlmodel import Session, func, select

from api.models import (
    Citation,
    Result,
    Run,
    RunMode,
    RunStatus,
    SurfaceCode,
    Tenant,
    TenantSurface,
)

# M2 dispatches Mode A on the OpenAI API surface only; more surfaces/modes
# join as their adapters land (M4+).
DISPATCHABLE_SURFACES = {SurfaceCode.openai_api}


def eligible_surfaces(session: Session, tenant: Tenant) -> list[str]:
    enabled = session.exec(
        select(TenantSurface.code).where(
            TenantSurface.tenant_id == tenant.id, TenantSurface.enabled == True  # noqa: E712
        )
    ).all()
    return sorted(
        {str(c) for c in enabled}
        & {str(s) for s in DISPATCHABLE_SURFACES}
        & set(tenant.approved_surfaces)
    )


def create_run(session: Session, tenant: Tenant, *, trigger: str = "manual") -> Run:
    """Creates the run row. Gated tenants are recorded with status `gated`,
    never silently skipped (§8). Caller commits and enqueues pending runs."""
    assert tenant.id is not None
    surfaces = eligible_surfaces(session, tenant)
    run = Run(tenant_id=tenant.id, trigger=trigger, surface_set=surfaces, mode_set=[RunMode.A])
    if not tenant.ai_processing_approved:
        run.status = RunStatus.gated
        run.error = "governance: ai_processing_approved is false for this tenant"
    elif not surfaces:
        run.status = RunStatus.failed
        run.error = "no dispatchable surface is both enabled and governance-approved"
    session.add(run)
    return run


def month_spend_usd(session: Session, tenant_id: int) -> float:
    """Spend attributed to the current UTC calendar month (§9 cap window)."""
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    total = session.exec(
        select(func.coalesce(func.sum(Run.cost_usd), 0.0)).where(
            Run.tenant_id == tenant_id, Run.created_at >= month_start  # pyright: ignore[reportArgumentType]
        )
    ).one()
    return float(total)


def run_detail_payload(session: Session, run: Run) -> dict:
    results = session.exec(
        select(Result).where(Result.run_id == run.id).order_by(Result.id)  # pyright: ignore[reportArgumentType]
    ).all()
    citations_by_result: dict[int, list[Citation]] = {}
    if results:
        for citation in session.exec(
            select(Citation).where(Citation.result_id.in_([r.id for r in results]))  # pyright: ignore[reportAttributeAccessIssue]
        ).all():
            citations_by_result.setdefault(citation.result_id, []).append(citation)
    return {
        "run": run,
        "results": [
            {
                "result": r,
                "citations": citations_by_result.get(r.id or -1, []),
            }
            for r in results
        ],
    }
