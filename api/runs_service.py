"""Run lifecycle shared by the admin trigger routes and the read endpoints.
Dispatch itself lives in worker/jobs.py."""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, func, select

from api.models import (
    Citation,
    Result,
    Run,
    RunMode,
    RunStatus,
    SpendEntry,
    SurfaceCode,
    Tenant,
    TenantSurface,
    utcnow,
)

# Surfaces with a working adapter, by mode. Mode A is the reliable API path
# across the major answer engines; Mode B is the fragile consumer-UI scrape.
MODE_A_SURFACES = {
    SurfaceCode.openai_api,
    SurfaceCode.perplexity_api,
    SurfaceCode.claude_api,
    SurfaceCode.gemini_api,
}
MODE_B_SURFACES = {
    SurfaceCode.chatgpt_web,
    SurfaceCode.perplexity_web,
    SurfaceCode.copilot_web,
    SurfaceCode.google_aio,
    SurfaceCode.google_ai_mode,
}
DISPATCHABLE_SURFACES = MODE_A_SURFACES | MODE_B_SURFACES


def eligible_surfaces(session: Session, tenant: Tenant) -> list[str]:
    from api.plans import cap_engines, limits_for

    enabled = session.exec(
        select(TenantSurface.code).where(
            TenantSurface.tenant_id == tenant.id, TenantSurface.enabled == True  # noqa: E712
        )
    ).all()
    eligible = sorted(
        {str(c) for c in enabled}
        & {str(s) for s in DISPATCHABLE_SURFACES}
        & set(tenant.approved_surfaces)
    )
    # The plan caps how many engines a run may dispatch (§pricing-model).
    return cap_engines(eligible, limits_for(tenant.plan).max_engines)


def create_run(session: Session, tenant: Tenant, *, trigger: str = "manual") -> Run:
    """Creates the run row. Gated tenants are recorded with status `gated`,
    never silently skipped (§8). Caller commits and enqueues pending runs."""
    assert tenant.id is not None
    surfaces = eligible_surfaces(session, tenant)
    modes = []
    if any(s in {str(m) for m in MODE_A_SURFACES} for s in surfaces):
        modes.append(RunMode.A)
    if any(s in {str(m) for m in MODE_B_SURFACES} for s in surfaces):
        modes.append(RunMode.B)
    run = Run(tenant_id=tenant.id, trigger=trigger, surface_set=surfaces, mode_set=modes)
    if not tenant.ai_processing_approved:
        run.status = RunStatus.gated
        run.error = "governance: ai_processing_approved is false for this tenant"
    elif not surfaces:
        run.status = RunStatus.failed
        run.error = "no dispatchable surface is both enabled and governance-approved"
    session.add(run)
    return run


# Hard ceiling on how long a run can be in flight (Mode A 3h + Mode B 4h job
# timeouts, plus slack). Past it a run is abandoned no matter what.
IN_FLIGHT_TTL = timedelta(hours=8)
# A run is committed before its job is enqueued and picked up; within this
# window it counts as live even if no job is visible yet.
START_GRACE = timedelta(minutes=2)
RUN_JOB_FUNCS = {"worker.jobs.run_mode_a", "worker.jobs.run_mode_b"}
ABANDONED_ERROR = (
    "abandoned: its worker job is gone (worker restarted or redeployed mid-run)"
)


class RunInFlight(Exception):
    """A run for this tenant is already pending or running."""

    def __init__(self, run: Run) -> None:
        super().__init__(f"Run #{run.id} is still {run.status}. Wait for it to finish.")
        self.run = run


def _as_utc(stamp: datetime) -> datetime:
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def runs_with_live_jobs(run_ids: set[int]) -> set[int] | None:
    """Which of these runs have a queued or executing RQ job. None when Redis
    can't be read (callers then assume live — never fail a run on a blip).

    A job whose worker was killed (deploy SIGKILL) drops out of the started
    registry once its heartbeat lapses (~90s, measured), so a killed run stops
    counting as live within a couple of minutes instead of blocking for hours."""
    if not run_ids:
        return set()
    try:
        from redis import Redis
        from rq import Queue
        from rq.job import Job
        from rq.registry import StartedJobRegistry

        from api.config import get_settings

        conn = Redis.from_url(
            get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2
        )
        job_ids: list[str] = []
        for name in ("default", "scrape"):
            queue = Queue(name, connection=conn)
            job_ids += queue.get_job_ids()
            job_ids += StartedJobRegistry(queue=queue).get_job_ids()  # drops dead jobs
        alive: set[int] = set()
        for job in Job.fetch_many(job_ids, connection=conn):
            if job is None or job.func_name not in RUN_JOB_FUNCS or not job.args:
                continue
            if job.args[0] in run_ids:
                alive.add(job.args[0])
        return alive
    except Exception:  # noqa: BLE001
        return None


def _is_abandoned(run: Run, alive: set[int] | None) -> bool:
    now = utcnow()
    if now - _as_utc(run.started_at or run.created_at) >= IN_FLIGHT_TTL:
        return True
    if now - _as_utc(run.created_at) < START_GRACE or alive is None:
        return False
    return run.id not in alive


def _mark_abandoned(session: Session, run: Run) -> None:
    run.status = RunStatus.failed
    run.error = ABANDONED_ERROR
    run.finished_at = utcnow()
    session.add(run)


def run_in_flight(session: Session, tenant_id: int) -> Run | None:
    """The tenant's live pending/running run, if any. Runs whose job is gone
    are marked failed on the way (caller commits), so a run killed by a deploy
    self-heals instead of blocking "Run now"."""
    rows = session.exec(
        select(Run)
        .where(
            Run.tenant_id == tenant_id,
            Run.status.in_([RunStatus.pending, RunStatus.running]),  # pyright: ignore[reportAttributeAccessIssue]
        )
        .order_by(Run.id.desc())  # pyright: ignore[reportAttributeAccessIssue, reportOptionalMemberAccess]
    ).all()
    if not rows:
        return None
    alive = runs_with_live_jobs({r.id for r in rows if r.id is not None})
    live: Run | None = None
    for run in rows:
        if _is_abandoned(run, alive):
            _mark_abandoned(session, run)
        elif live is None:
            live = run
    return live


def reap_abandoned_runs(session: Session) -> int:
    """Fail every pending/running run (any tenant) whose job is gone. Called
    from the scheduler tick so the Runs page stops saying "running" for a run
    a deploy killed, without anyone having to click."""
    rows = session.exec(
        select(Run).where(
            Run.status.in_([RunStatus.pending, RunStatus.running])  # pyright: ignore[reportAttributeAccessIssue]
        )
    ).all()
    if not rows:
        return 0
    alive = runs_with_live_jobs({r.id for r in rows if r.id is not None})
    reaped = [r for r in rows if _is_abandoned(r, alive)]
    for run in reaped:
        _mark_abandoned(session, run)
    if reaped:
        session.commit()
    return len(reaped)


def trigger_run(session: Session, tenant: Tenant, *, trigger: str = "manual") -> Run:
    """Create, commit, and dispatch a run — shared by the admin trigger route
    and the scheduler. Gated/failed runs are recorded and never enqueued.

    Raises RunInFlight when the tenant already has a live run: a double-click
    (or a schedule firing mid-run) must not start a second, double-spending
    run over the same prompts."""
    from api.queue import enqueue_run, enqueue_run_mode_b  # avoid import cycle

    assert tenant.id is not None
    # Serialize concurrent triggers per tenant (Postgres row lock; SQLite has
    # a single writer anyway) so two simultaneous clicks can't both pass.
    session.exec(
        select(Tenant).where(Tenant.id == tenant.id).with_for_update()
    ).one()
    existing = run_in_flight(session, tenant.id)
    if existing is not None:
        session.commit()  # keep any abandoned runs it reaped; releases the lock
        raise RunInFlight(existing)

    run = create_run(session, tenant, trigger=trigger)
    session.add(run)
    session.commit()
    session.refresh(run)
    if run.status == RunStatus.pending:
        assert run.id is not None
        try:
            if RunMode.A in run.mode_set:
                enqueue_run(run.id)
            else:
                enqueue_run_mode_b(run.id)
        except Exception as exc:  # noqa: BLE001 — record it; never strand a pending run
            run.status = RunStatus.failed
            run.error = f"could not queue the run (is Redis up?): {type(exc).__name__}"[:500]
            run.finished_at = utcnow()
            session.add(run)
            session.commit()
            session.refresh(run)
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
    # Paid calls outside runs (content drafting) count toward the cap too.
    other = session.exec(
        select(func.coalesce(func.sum(SpendEntry.cost_usd), 0.0)).where(
            SpendEntry.tenant_id == tenant_id,
            SpendEntry.created_at >= month_start,  # pyright: ignore[reportArgumentType]
        )
    ).one()
    return float(total) + float(other)


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
