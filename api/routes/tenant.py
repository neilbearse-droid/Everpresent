"""Org-scoped config reads. The tenant always comes from the session's org
context (api.tenancy), never from a request parameter."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from api import dashboards_service
from api.db import get_session
from api.models import (
    BrandProfile,
    Competitor,
    ContentDraft,
    ContentDraftStatus,
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


@router.post("/agent-logs")
async def upload_agent_logs(request: Request, ctx: Ctx, session: Db) -> dict:
    """Upload an access log (raw or .gz): Apache/Nginx, Cloudflare Logpush,
    Vercel, CloudFront or JSON lines. Only AI-bot hits are kept."""
    from api.agent_analytics import UploadError, ingest_stream

    try:
        summary = await ingest_stream(session, ctx.tenant_id, request.stream())
    except UploadError as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    session.commit()
    return summary


@router.get("/agent-analytics")
def agent_analytics(ctx: Ctx, session: Db, days: int = 30) -> dict:
    from api.agent_analytics import agent_analytics as _report

    return _report(session, ctx.tenant_id, days=max(1, min(days, 365)))


@router.get("/answer-shape")
def answer_shape_route(ctx: Ctx, session: Db, days: int = 60) -> dict:
    """How answers are built per engine and served model, model changes,
    memory vs search, and the themes/objections around the brand."""
    from api.answer_shape_service import answer_shape

    return answer_shape(session, ctx.tenant_id, days=max(7, min(days, 180)))


@router.get("/own-pages")
def own_pages_route(ctx: Ctx, session: Db, days: int = 30) -> dict:
    """The brand's own pages AI answers use, and whether each is fit for it."""
    from api.own_pages_service import own_pages

    return own_pages(session, ctx.tenant_id, days=max(7, min(days, 180)))


@router.get("/first-party")
def first_party_route(ctx: Ctx, session: Db) -> dict:
    from api.first_party_service import SOURCES, first_party_summary

    return {**first_party_summary(session, ctx.tenant_id), "available": SOURCES}


@router.post("/first-party")
async def import_first_party(request: Request, ctx: Ctx, session: Db, source: str) -> dict:
    """Import a CSV/TSV export from Search Console, Bing Webmaster Tools,
    Merchant Center, Cloudflare or GA4. Columns are mapped by name."""
    from starlette.concurrency import run_in_threadpool

    from api.first_party_service import MAX_BYTES, ImportError_, import_export

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="export too large (max 20 MB)")
    try:
        summary = await run_in_threadpool(import_export, session, ctx.tenant_id, source,
                                          bytes(body))
    except ImportError_ as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return summary


@router.delete("/first-party")
def clear_first_party(ctx: Ctx, session: Db, source: str) -> dict:
    from sqlmodel import delete

    from api.models import FirstPartyDaily

    res = session.exec(delete(FirstPartyDaily).where(  # pyright: ignore[reportCallIssue,reportArgumentType]
        FirstPartyDaily.tenant_id == ctx.tenant_id,  # pyright: ignore[reportArgumentType]
        FirstPartyDaily.source == source,  # pyright: ignore[reportArgumentType]
    ))
    session.commit()
    return {"deleted": res.rowcount}  # pyright: ignore[reportAttributeAccessIssue]


@router.get("/overview")
def overview(ctx: Ctx, session: Db, start: str | None = None, end: str | None = None) -> dict:
    return dashboards_service.overview(session, ctx.tenant_id, start, end)


@router.get("/engine-modes")
def engine_modes(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.engine_modes(session, ctx.tenant_id, start, end)


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


@router.get("/fanout")
def fanout(ctx: Ctx, session: Db) -> dict:
    return dashboards_service.fanout_report(session, ctx.tenant_id)


@router.get("/fanout-scorecard")
def fanout_scorecard(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.fanout_scorecard(session, ctx.tenant_id, start, end)


@router.get("/accuracy")
def accuracy(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.accuracy_report(session, ctx.tenant_id, start, end)


@router.get("/routing")
def routing(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.routing_report(session, ctx.tenant_id, start, end)


@router.get("/whitespace")
def whitespace(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.whitespace_report(session, ctx.tenant_id, start, end)


@router.get("/brand")
def brand(
    ctx: Ctx, session: Db, start: str | None = None, end: str | None = None
) -> dict:
    return dashboards_service.brand_report(session, ctx.tenant_id, start, end)


@router.get("/content/drafts")
def content_drafts(ctx: Ctx, session: Db) -> list[ContentDraft]:
    from api.content_service import list_drafts

    return list_drafts(session, ctx.tenant_id)


@router.post("/content/accuracy/{fact_id}/draft")
def generate_accuracy_draft(fact_id: int, ctx: Ctx, session: Db) -> ContentDraft:
    """Close the loop: generate the corrective content for an accuracy gap.
    Governed — returns 409 with a clear reason when the tenant/config can't."""
    from api.content_service import ContentGenUnavailable
    from api.content_service import generate_accuracy_draft as _gen

    if ctx.tenant is None or not ctx.tenant.ai_processing_approved:
        raise HTTPException(status_code=403, detail="AI processing not approved for this tenant")
    try:
        return _gen(session, ctx.tenant, fact_id)
    except ContentGenUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/content/fanout/{shard_id}/draft")
def generate_shard_draft(shard_id: int, ctx: Ctx, session: Db) -> ContentDraft:
    """Close the loop on a lost fan-out shard (M25c): a brief that answers the
    sub-query the engine searched. Governed — 409 with a clear reason when the
    tenant/config can't, or when the shard isn't a measured miss."""
    from api.content_service import ContentGenUnavailable
    from api.content_service import generate_shard_draft as _gen

    if ctx.tenant is None or not ctx.tenant.ai_processing_approved:
        raise HTTPException(status_code=403, detail="AI processing not approved for this tenant")
    try:
        return _gen(session, ctx.tenant, shard_id)
    except ContentGenUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class ContentDraftStatusPatch(BaseModel):
    status: ContentDraftStatus


@router.patch("/content/drafts/{draft_id}")
def update_content_draft(
    draft_id: int, payload: ContentDraftStatusPatch, ctx: Ctx, session: Db
) -> ContentDraft:
    draft = session.get(ContentDraft, draft_id)
    if draft is None or draft.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="No such draft")
    draft.status = payload.status
    draft.updated_at = utcnow()
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


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
            parsed = datetime.fromisoformat(payload.shipped_at)
            # Convert an offset-aware time to UTC; treat a bare date as UTC.
            shipped = parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail="shipped_at must be an ISO date (YYYY-MM-DD)"
            ) from exc
    url = payload.url.strip()
    if url and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="url must start with http:// or https://")
    item = Intervention(
        tenant_id=ctx.tenant_id,
        query_text=text,
        description=payload.description.strip(),
        url=url,
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
            .order_by(
                col(Recommendation.priority).desc(),
                col(Recommendation.gap_ref),
            )
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
