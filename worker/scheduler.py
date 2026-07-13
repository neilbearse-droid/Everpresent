"""Schedule loop (M5): fires cron run_schedules and the nightly BigQuery
mirror. Runs as its own small compose service; tick() is pure enough to test
with a fake clock."""

import time
from datetime import UTC, datetime

import structlog
from croniter import croniter
from sqlmodel import Session, select

from api.config import get_settings
from api.db import get_engine
from api.models import MirrorState, RunSchedule, Tenant, utcnow
from api.runs_service import trigger_run

log = structlog.get_logger()

TICK_SECONDS = 30
MIRROR_STATE_KEY = "_last_mirror_day"


def next_fire(cron_expr: str, after: datetime) -> datetime:
    return croniter(cron_expr, after).get_next(datetime)


def tick(session: Session, now: datetime | None = None) -> list[int]:
    """Fires due schedules; returns triggered run ids."""
    now = now or datetime.now(UTC)
    triggered: list[int] = []
    for schedule in session.exec(select(RunSchedule).where(RunSchedule.enabled == True)).all():  # noqa: E712
        if schedule.next_run_at is None:
            # Newly created or re-enabled: arm without firing retroactively.
            schedule.next_run_at = next_fire(schedule.cron_expr, now)
            session.add(schedule)
            session.commit()
            continue
        next_at = schedule.next_run_at
        if next_at.tzinfo is None:
            next_at = next_at.replace(tzinfo=UTC)
        if next_at > now:
            continue
        tenant = session.get(Tenant, schedule.tenant_id)
        if tenant is not None:
            run = trigger_run(session, tenant, trigger="schedule")
            log.info("schedule.fired", tenant=tenant.slug, run_id=run.id, status=run.status)
            if run.id is not None:
                triggered.append(run.id)
        schedule.last_triggered_at = now
        schedule.next_run_at = next_fire(schedule.cron_expr, now)
        session.add(schedule)
        session.commit()

    _maybe_enqueue_mirror(session, now)
    return triggered


def _maybe_enqueue_mirror(session: Session, now: datetime) -> None:
    settings = get_settings()
    if not settings.bigquery_project:
        return
    if now.hour < settings.mirror_hour_utc:
        return
    day_stamp = int(now.strftime("%Y%m%d"))
    state = session.exec(
        select(MirrorState).where(MirrorState.table_name == MIRROR_STATE_KEY)
    ).first()
    if state is not None and state.last_id >= day_stamp:
        return
    if state is None:
        state = MirrorState(table_name=MIRROR_STATE_KEY)
    state.last_id = day_stamp
    state.updated_at = utcnow()
    session.add(state)
    session.commit()
    from api.queue import get_queue

    get_queue().enqueue("worker.mirror.mirror_to_bigquery", job_timeout=30 * 60)
    log.info("mirror.enqueued", day=day_stamp)


def run() -> None:
    log.info("scheduler.start", tick_seconds=TICK_SECONDS)
    while True:
        try:
            with Session(get_engine()) as session:
                tick(session)
        except Exception:  # noqa: BLE001 — the loop must survive anything
            log.exception("scheduler.tick_failed")
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    run()
