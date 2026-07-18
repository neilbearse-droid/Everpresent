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
from api.models import Citation, MirrorState, RunSchedule, Tenant, utcnow
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
            from api.plans import limits_for
            from api.scheduling import runs_in_last_day

            cap = limits_for(tenant.plan).max_runs_per_day
            # Backstop the schedule-save gate: a plan downgrade or a schedule
            # created before the gate could still over-fire. Skip this fire if
            # the daily cap is already spent.
            if cap is not None and runs_in_last_day(session, tenant.id) >= cap:
                log.info("schedule.skipped_frequency_cap", tenant=tenant.slug, cap=cap)
            else:
                run = trigger_run(session, tenant, trigger="schedule")
                log.info("schedule.fired", tenant=tenant.slug, run_id=run.id, status=run.status)
                if run.id is not None:
                    triggered.append(run.id)
                # Only stamp last_triggered_at when a run actually fired — a
                # cap-skipped tick never triggered anything (§audit low).
                schedule.last_triggered_at = now
        # Always advance next_run_at (even on skip/no-tenant) so a due schedule
        # doesn't re-evaluate every tick.
        schedule.next_run_at = next_fire(schedule.cron_expr, now)
        session.add(schedule)
        session.commit()

    _maybe_enqueue_nightly(session, now)
    return triggered


def _maybe_enqueue_nightly(session: Session, now: datetime) -> None:
    """Once-a-day, after mirror_hour_utc: enqueue the BigQuery mirror, the GA4
    outcome pull, and the Power Pages presence crawl. A single day-watermark
    gates all three; the first two are skipped when their integration isn't
    configured, the crawl needs none."""
    settings = get_settings()
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
    from api.queue import get_queue

    # Enqueue FIRST, then advance the day-watermark (§audit low). Committing the
    # watermark before enqueue meant a Redis/enqueue failure left the day
    # stamped-done, silently skipping that day's mirror/GA4/crawl until tomorrow.
    queue = get_queue()
    if settings.bigquery_project:
        queue.enqueue("worker.mirror.mirror_to_bigquery", job_timeout=30 * 60)
        log.info("mirror.enqueued", day=day_stamp)
    if settings.google_service_account_json:
        queue.enqueue("worker.ga4_pull.pull_ga4_referrals", job_timeout=15 * 60)
        log.info("ga4.enqueued", day=day_stamp)
    # Presence crawl for every tenant that has citation data to audit.
    tenant_ids = {tid for tid in session.exec(select(Citation.tenant_id).distinct()).all()}
    for tid in sorted(tenant_ids):
        queue.enqueue("worker.page_crawl.crawl_power_pages", tid, job_timeout=15 * 60)
    if tenant_ids:
        log.info("page_crawl.enqueued", day=day_stamp, tenants=len(tenant_ids))

    state.last_id = day_stamp
    state.updated_at = utcnow()
    session.add(state)
    session.commit()


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
