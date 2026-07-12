"""Org-scoped config reads. The tenant always comes from the session's org
context (api.tenancy), never from a request parameter."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from api.db import get_session
from api.models import (
    BrandProfile,
    Competitor,
    Persona,
    Query,
    Result,
    Run,
    TenantSurface,
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
    envelope = read_raw_envelope(result.raw_uri) if result.raw_uri else None
    if envelope is None:
        raise HTTPException(status_code=404, detail="Raw payload not available")
    return envelope
