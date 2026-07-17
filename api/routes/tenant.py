"""Org-scoped config reads. The tenant always comes from the session's org
context (api.tenancy), never from a request parameter."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, func, select

from api import dashboards_service
from api.db import get_session
from api.models import (
    BrandProfile,
    Competitor,
    Intervention,
    Persona,
    Query,
    Recommendation,
    RecommendationStatus,
    Result,
    Run,
    TenantSurface,
    utcnow,
)
from api.runs_service import run_detail_payload
from api.storage import read_raw_envelope
from api.tenancy import TenantContext, get_current_tenant

router = APIRouter(prefix="/tenant")

Ctx = Annotated[TenantContext, Depends(get_current_tenant)]
Db = Annotated[Session, Depends(get_session)]


@router.get("")
def tenant_summary(ctx: Ctx, session: Db) -> dict:
    def count(model) -> int:
        return session.exec(
            select(func.count()).select_from(model).where(model.tenant_id == ctx.tenant_id)
        ).one()

    brand = session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == ctx.tenant_id)
    ).first()
    return {
        "name": ctx.tenant.name,
        "slug": ctx.tenant.slug,
        "status": ctx.tenant.status,
        "role": ctx.role,
        "brand_name": brand.brand_name if brand else None,
        "ai_processing_approved": ctx.tenant.ai_processing_approved,
        "counts": {
            "competitors": count(Competitor),
            "personas": count(Persona),
            "queries": count(Query),
        },
    }


@router.get("/brand-profile")
def brand_profile(ctx: Ctx, session: Db) -> BrandProfile | None:
    return session.exec(
        select(BrandProfile).where(BrandProfile.tenant_id == ctx.tenant_id)
    ).first()


@router.get("/competitors")
def competitors(ctx: Ctx, session: Db) -> list[Competitor]:
    return list(
        session.exec(select(Competitor).where(Competitor.tenant_id == ctx.tenant_id)).all()
    )


@router.get("/personas")
def personas(ctx: Ctx, session: Db) -> list[Persona]:
    return list(session.exec(select(Persona).where(Persona.tenant_id == ctx.tenant_id)).all())


@router.get("/queries")
def queries(ctx: Ctx, session: Db) -> list[Query]:
    return list(session.exec(select(Query).where(Query.tenant_id == ctx.tenant_id)).all())


@router.get("/surfaces")
def surfaces(ctx: Ctx, session: Db) -> list[TenantSurface]:
    return list(
        session.exec(select(TenantSurface).where(TenantSurface.tenant_id == ctx.tenant_id)).all()
    )


@router.get("/overview")
def overview(ctx: Ctx, session: Db, start: str | None = None, end: str | None = None) -> dict:
    return dashboards_service.overview(session, ctx.tenant_id, start, end)


@router.get("/personas-intel")
def personas_intel(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.personas(session, ctx.tenant_id, start, end)


@router.get("/queries-intel")
def queries_intel(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.queries_intel(session, ctx.tenant_id, start, end)


@router.get("/engine-scorecard")
def engine_scorecard(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.engine_scorecard(session, ctx.tenant_id, start, end)


@router.get("/action-plan")
def action_plan(ctx: Ctx, session: Db) -> dict:
    return dashboards_service.action_plan(session, ctx.tenant_id)


@router.get("/kpi-scorecard")
def kpi_scorecard(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.kpi_scorecard(session, ctx.tenant_id, start, end)


@router.get("/outcome")
def outcome(ctx: Ctx, session: Db, start: str | None = None, end: str | None = None) -> dict:
    return dashboards_service.outcome(session, ctx.tenant_id, start, end)


class InterventionCreate(BaseModel):
    query_text: str
    description: str = ""
    url: str = ""
    shipped_at: str | None = None  # ISO date; defaults to today


@router.get("/interventions")
def list_interventions(ctx: Ctx, session: Db) -> dict:
    return dashboards_service.interventions_report(session, ctx.tenant_id)


@router.post("/interventions", status_code=201)
def create_intervention(payload: InterventionCreate, ctx: Ctx, session: Db) -> Intervention:
    from datetime import UTC, datetime

    text = payload.query_text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="query_text is required")
    shipped = utcnow()
    if payload.shipped_at:
        try:
            shipped = datetime.fromisoformat(payload.shipped_at).replace(tzinfo=UTC)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="shipped_at must be an ISO date (YYYY-MM-DD)"
            ) from exc
    item = Intervention(
        tenant_id=ctx.tenant_id,
        query_text=text,
        description=payload.description.strip(),
        url=payload.url.strip(),
        shipped_at=shipped,
        created_by=ctx.authed.user.email,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/interventions/{intervention_id}", status_code=204)
def delete_intervention(intervention_id: int, ctx: Ctx, session: Db) -> None:
    item = session.get(Intervention, intervention_id)
    if item is None or item.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="No such intervention")
    session.delete(item)
    session.commit()


@router.get("/recommendations")
def recommendations(ctx: Ctx, session: Db) -> list[Recommendation]:
    return list(
        session.exec(
            select(Recommendation)
            .where(Recommendation.tenant_id == ctx.tenant_id)
            .order_by(Recommendation.status, Recommendation.branch, Recommendation.gap_ref)  # pyright: ignore[reportArgumentType]
        ).all()
    )


class RecommendationStatusPatch(BaseModel):
    status: RecommendationStatus


@router.patch("/recommendations/{rec_id}")
def update_recommendation(
    rec_id: int, payload: RecommendationStatusPatch, ctx: Ctx, session: Db
) -> Recommendation:
    rec = session.get(Recommendation, rec_id)
    if rec is None or rec.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="No such recommendation")
    rec.status = payload.status
    rec.updated_at = utcnow()
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


@router.get("/citations-intel")
def citations_intel(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.citations_intel(session, ctx.tenant_id, start, end)


@router.get("/reports/results.csv")
def results_csv(ctx: Ctx, session: Db) -> Response:
    from api.reports import build_results_csv

    return Response(
        content=build_results_csv(session, ctx.tenant_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{ctx.tenant.slug}-results.csv"'
        },
    )


@router.get("/reports/visibility.csv")
def visibility_csv(ctx: Ctx, session: Db) -> Response:
    from api.reports import build_visibility_csv

    return Response(
        content=build_visibility_csv(session, ctx.tenant_id),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{ctx.tenant.slug}-visibility.csv"'
        },
    )


@router.get("/reports/summary.pdf")
def summary_pdf(ctx: Ctx, session: Db) -> Response:
    from api.reports import build_summary_pdf

    return Response(
        content=build_summary_pdf(session, ctx.tenant),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{ctx.tenant.slug}-summary.pdf"'
        },
    )


@router.get("/runs")
def runs(ctx: Ctx, session: Db) -> list[Run]:
    return list(
        session.exec(
            select(Run)
            .where(Run.tenant_id == ctx.tenant_id)
            .order_by(Run.id.desc())  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
            .limit(100)
        ).all()
    )


@router.get("/runs/{run_id}")
def run_detail(run_id: int, ctx: Ctx, session: Db) -> dict:
    run = session.get(Run, run_id)
    if run is None or run.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="No such run")
    return run_detail_payload(session, run)


@router.get("/results/{result_id}/raw")
def result_raw(result_id: int, ctx: Ctx, session: Db) -> dict:
    result = session.get(Result, result_id)
    if result is None or result.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="No such result")
    envelope = read_raw_envelope(result.raw_uri, session=session) if result.raw_uri else None
    if envelope is None:
        raise HTTPException(status_code=404, detail="Raw payload not available")
    return envelope
