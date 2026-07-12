"""Org-scoped config reads. The tenant always comes from the session's org
context (api.tenancy), never from a request parameter."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from api.db import get_session
from api.models import BrandProfile, Competitor, Persona, Query, TenantSurface
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
