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
    Result,
    Run,
    RunSchedule,
    SurfaceCode,
    Tenant,
    TenantStatus,
    TenantSurface,
)
from api.runs_service import month_spend_usd, run_detail_payload, trigger_run
from api.storage import read_raw_envelope
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


def _full_surface_catalog(session: Session, tid: int) -> list[TenantSurface]:
    """Every surface in the code catalog, in enum order (API engines first),
    carrying this tenant's enabled flag. Surfaces added after a tenant was
    imported have no row yet — synthesize a disabled one so they still appear
    as a toggle, instead of being invisible until a config re-import."""
    existing = {
        row.code: row
        for row in session.exec(select(TenantSurface).where(TenantSurface.tenant_id == tid)).all()
    }
    catalog: list[TenantSurface] = []
    for code in SurfaceCode:
        catalog.append(
            existing.get(code) or TenantSurface(tenant_id=tid, code=code, enabled=False)
        )
    return catalog


@router.get("/tenants/{slug}")
def tenant_detail(slug: str, session: Db) -> dict:
    tenant = _tenant_or_404(session, slug)
    tid = tenant.id
    assert tid is not None
    return {
        "tenant": tenant,
        "brand_profile": session.exec(
            select(BrandProfile).where(BrandProfile.tenant_id == tid)
        ).first(),
        "competitors": session.exec(select(Competitor).where(Competitor.tenant_id == tid)).all(),
        "personas": session.exec(select(Persona).where(Persona.tenant_id == tid)).all(),
        "queries": session.exec(select(Query).where(Query.tenant_id == tid)).all(),
        "surfaces": _full_surface_catalog(session, tid),
    }


class TenantPatch(BaseModel):
    name: str | None = None
    status: TenantStatus | None = None
    clerk_org_id: str | None = None
    ai_processing_approved: bool | None = None
    approved_surfaces: list[SurfaceCode] | None = None
    approved_utility_models: list[str] | None = None
    monthly_spend_cap_usd: float | None = None
    notify_emails: list[str] | None = None


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
    if payload.monthly_spend_cap_usd is not None:
        if payload.monthly_spend_cap_usd < 0:
            raise HTTPException(status_code=422, detail="Spend cap must be >= 0")
        tenant.monthly_spend_cap_usd = payload.monthly_spend_cap_usd
        changed.append("monthly_spend_cap_usd")
    if payload.notify_emails is not None:
        cleaned = [e.strip() for e in payload.notify_emails if e.strip()]
        if any("@" not in e for e in cleaned):
            raise HTTPException(status_code=422, detail="notify_emails must be email addresses")
        tenant.notify_emails = cleaned
        changed.append("notify_emails")

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


@router.post("/tenants/{slug}/runs", status_code=201)
def trigger_run_route(slug: str, session: Db, admin: Admin) -> Run:
    tenant = _tenant_or_404(session, slug)
    run = trigger_run(session, tenant, trigger="manual")
    write_audit(
        session,
        tenant_id=tenant.id,
        actor=admin.user.email,
        action=f"run.trigger {slug} -> {run.status}",
    )
    session.commit()
    session.refresh(run)
    return run


@router.get("/tenants/{slug}/runs")
def list_runs(slug: str, session: Db) -> dict:
    tenant = _tenant_or_404(session, slug)
    assert tenant.id is not None
    runs = session.exec(
        select(Run)
        .where(Run.tenant_id == tenant.id)
        .order_by(Run.id.desc())  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
        .limit(100)
    ).all()
    return {
        "runs": runs,
        "month_spend_usd": month_spend_usd(session, tenant.id),
        "monthly_spend_cap_usd": tenant.monthly_spend_cap_usd,
    }


@router.post("/runs/{run_id}/process")
def reprocess_run(run_id: int, session: Db, admin: Admin) -> dict:
    """Re-run processing over a stored run — applies detector/classifier
    upgrades to history without re-spending on retrieval."""
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such run")
    from api.processing_service import process_run

    counts = process_run(session, run)
    run.counts = {**run.counts, **counts}
    session.add(run)
    write_audit(
        session, tenant_id=run.tenant_id, actor=admin.user.email, action=f"run.process {run_id}"
    )
    session.commit()
    return counts


@router.get("/runs/{run_id}")
def run_detail(run_id: int, session: Db) -> dict:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such run")
    return run_detail_payload(session, run)


@router.get("/results/{result_id}/raw")
def result_raw(result_id: int, session: Db) -> dict:
    result = session.get(Result, result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No such result")
    envelope = read_raw_envelope(result.raw_uri, session=session) if result.raw_uri else None
    if envelope is None:
        raise HTTPException(status_code=404, detail="Raw payload not available")
    return envelope


class SchedulePut(BaseModel):
    cron_expr: str
    enabled: bool = True


@router.get("/tenants/{slug}/schedule")
def get_schedule(slug: str, session: Db) -> RunSchedule | None:
    tenant = _tenant_or_404(session, slug)
    return session.exec(
        select(RunSchedule).where(RunSchedule.tenant_id == tenant.id)
    ).first()


@router.put("/tenants/{slug}/schedule")
def put_schedule(slug: str, payload: SchedulePut, session: Db, admin: Admin) -> RunSchedule:
    from croniter import croniter

    tenant = _tenant_or_404(session, slug)
    cron_expr = payload.cron_expr.strip()
    if not croniter.is_valid(cron_expr):
        raise HTTPException(status_code=422, detail=f"Not a valid cron expression: {cron_expr!r}")
    assert tenant.id is not None
    schedule = session.exec(
        select(RunSchedule).where(RunSchedule.tenant_id == tenant.id)
    ).first()
    if schedule is None:
        schedule = RunSchedule(tenant_id=tenant.id, cron_expr=cron_expr, enabled=payload.enabled)
    else:
        schedule.cron_expr = cron_expr
        schedule.enabled = payload.enabled
        schedule.next_run_at = None  # re-armed by the scheduler from the new cron
    session.add(schedule)
    write_audit(
        session,
        tenant_id=tenant.id,
        actor=admin.user.email,
        action=f"schedule.put {slug} {cron_expr} enabled={payload.enabled}",
    )
    session.commit()
    session.refresh(schedule)
    return schedule


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

    # Enabling a surface also governance-approves it (the superadmin is the
    # governance authority here); disabling removes the approval. A run needs
    # a surface both enabled and in approved_surfaces — keeping them in lockstep
    # from this single toggle avoids a hidden second step. The master gate
    # (ai_processing_approved) is separate and unaffected.
    approved = [s for s in tenant.approved_surfaces if s != payload.code.value]
    if payload.enabled:
        approved.append(payload.code.value)
    tenant.approved_surfaces = sorted(set(approved))
    session.add(tenant)

    write_audit(
        session,
        tenant_id=tenant.id,
        actor=admin.user.email,
        action=f"tenant.surface {slug} {payload.code}={'on' if payload.enabled else 'off'}",
    )
    session.commit()
    session.refresh(row)
    return row
