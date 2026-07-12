"""Superadmin-only tenant administration (§7.2). Every mutation writes an
audit_log row in the same transaction."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.audit import write_audit
from api.auth import AuthedUser, require_superadmin
from api.db import get_session
from api.models import (
    BrandProfile,
    Competitor,
    Persona,
    Query,
    SurfaceCode,
    Tenant,
    TenantStatus,
    TenantSurface,
)
from api.yaml_import import ConfigImportError, import_config, parse_config_yaml
from engine.llm.policy import RUNTIME_LLM_ALLOWLIST

router = APIRouter(prefix="/admin", dependencies=[Depends(require_superadmin)])

Db = Annotated[Session, Depends(get_session)]
Admin = Annotated[AuthedUser, Depends(require_superadmin)]


def _tenant_or_404(session: Session, slug: str) -> Tenant:
    tenant = session.exec(select(Tenant).where(Tenant.slug == slug)).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="No such tenant")
    return tenant


@router.get("/tenants")
def list_tenants(session: Db) -> list[Tenant]:
    return list(session.exec(select(Tenant).order_by(Tenant.slug)).all())  # pyright: ignore[reportArgumentType]


class TenantCreate(BaseModel):
    name: str
    slug: str


@router.post("/tenants", status_code=201)
def create_tenant(payload: TenantCreate, session: Db, admin: Admin) -> Tenant:
    slug = payload.slug.strip().lower()
    if not slug or not slug.replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="Slug must be alphanumeric-with-dashes")
    if session.exec(select(Tenant).where(Tenant.slug == slug)).first():
        raise HTTPException(status_code=409, detail="Slug already exists")
    tenant = Tenant(name=payload.name.strip(), slug=slug)
    session.add(tenant)
    session.flush()
    write_audit(
        session, tenant_id=tenant.id, actor=admin.user.email, action=f"tenant.create {slug}"
    )
    session.commit()
    session.refresh(tenant)
    return tenant


@router.get("/tenants/{slug}")
def tenant_detail(slug: str, session: Db) -> dict:
    tenant = _tenant_or_404(session, slug)
    tid = tenant.id
    return {
        "tenant": tenant,
        "brand_profile": session.exec(
            select(BrandProfile).where(BrandProfile.tenant_id == tid)
        ).first(),
        "competitors": session.exec(select(Competitor).where(Competitor.tenant_id == tid)).all(),
        "personas": session.exec(select(Persona).where(Persona.tenant_id == tid)).all(),
        "queries": session.exec(select(Query).where(Query.tenant_id == tid)).all(),
        "surfaces": session.exec(select(TenantSurface).where(TenantSurface.tenant_id == tid)).all(),
    }


class TenantPatch(BaseModel):
    name: str | None = None
    status: TenantStatus | None = None
    clerk_org_id: str | None = None
    ai_processing_approved: bool | None = None
    approved_surfaces: list[SurfaceCode] | None = None
    approved_utility_models: list[str] | None = None


@router.patch("/tenants/{slug}")
def patch_tenant(slug: str, payload: TenantPatch, session: Db, admin: Admin) -> Tenant:
    tenant = _tenant_or_404(session, slug)
    changed: list[str] = []

    if payload.approved_utility_models is not None:
        # Governance may only approve models from the §4 runtime allowlist —
        # this is the one place a forbidden build-time model could sneak into
        # tenant config, so it can't.
        illegal = set(payload.approved_utility_models) - set(RUNTIME_LLM_ALLOWLIST)
        if illegal:
            raise HTTPException(
                status_code=422,
                detail=f"Not in the runtime model allowlist: {sorted(illegal)}",
            )
        tenant.approved_utility_models = payload.approved_utility_models
        changed.append("approved_utility_models")

    if payload.name is not None:
        tenant.name = payload.name.strip()
        changed.append("name")
    if payload.status is not None:
        tenant.status = payload.status
        changed.append("status")
    if payload.clerk_org_id is not None:
        tenant.clerk_org_id = payload.clerk_org_id.strip() or None
        changed.append("clerk_org_id")
    if payload.ai_processing_approved is not None:
        tenant.ai_processing_approved = payload.ai_processing_approved
        changed.append("ai_processing_approved")
    if payload.approved_surfaces is not None:
        tenant.approved_surfaces = [s.value for s in payload.approved_surfaces]
        changed.append("approved_surfaces")

    session.add(tenant)
    write_audit(
        session,
        tenant_id=tenant.id,
        actor=admin.user.email,
        action=f"tenant.update {slug}: {', '.join(changed) or 'no-op'}",
    )
    session.commit()
    session.refresh(tenant)
    return tenant


@router.post("/tenants/{slug}/import-yaml")
def import_yaml(
    slug: str,
    session: Db,
    admin: Admin,
    yaml_text: Annotated[str, Body(media_type="text/plain")],
) -> dict:
    tenant = _tenant_or_404(session, slug)
    try:
        spec = parse_config_yaml(yaml_text)
    except ConfigImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    counts = import_config(session, tenant, spec)
    write_audit(
        session, tenant_id=tenant.id, actor=admin.user.email, action=f"tenant.import-yaml {slug}"
    )
    session.commit()
    return {"imported": counts, "brand": spec.brand.name}


class SurfaceToggle(BaseModel):
    code: SurfaceCode
    enabled: bool


@router.patch("/tenants/{slug}/surfaces")
def toggle_surface(slug: str, payload: SurfaceToggle, session: Db, admin: Admin) -> TenantSurface:
    tenant = _tenant_or_404(session, slug)
    row = session.exec(
        select(TenantSurface).where(
            TenantSurface.tenant_id == tenant.id, TenantSurface.code == payload.code
        )
    ).first()
    if row is None:
        row = TenantSurface(tenant_id=tenant.id, code=payload.code, enabled=payload.enabled)  # pyright: ignore[reportArgumentType]
    else:
        row.enabled = payload.enabled
    session.add(row)
    write_audit(
        session,
        tenant_id=tenant.id,
        actor=admin.user.email,
        action=f"tenant.surface {slug} {payload.code}={'on' if payload.enabled else 'off'}",
    )
    session.commit()
    session.refresh(row)
    return row
