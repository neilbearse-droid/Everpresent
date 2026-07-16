"""Schedule-frequency policy (§pricing-model). A plan caps how often scheduled
runs may fire; enforced at schedule-save time and, as a backstop, in the
scheduler tick (which also protects against plan downgrades and pre-existing
schedules)."""

from datetime import UTC, datetime, timedelta

from croniter import croniter
from sqlmodel import Session, func, select

from api.models import Run

# Fixed reference instant; scheduling policy must not depend on wall-clock.
_REF = datetime(2025, 1, 1, tzinfo=UTC)
_SAMPLE = 24  # fires to inspect — enough to catch same-day bursts


def cron_within_cap(cron_expr: str, max_runs_per_day: int | None) -> bool:
    """True if the cron never fires more often than the plan allows. Checks the
    minimum gap between consecutive fires against 24h / max_runs_per_day, so a
    burst (e.g. eight fires in one hour) is caught, not just the weekly average."""
    if max_runs_per_day is None:
        return True
    required = timedelta(hours=24) / max_runs_per_day
    it = croniter(cron_expr, _REF)
    prev = it.get_next(datetime)
    for _ in range(_SAMPLE):
        nxt = it.get_next(datetime)
        if (nxt - prev) < required * 0.99:  # small tolerance for DST edges
            return False
        prev = nxt
    return True


def runs_in_last_day(session: Session, tenant_id: int) -> int:
    since = datetime.now(UTC) - timedelta(hours=24)
    return session.exec(
        select(func.count()).select_from(Run).where(
            Run.tenant_id == tenant_id,
            Run.created_at >= since,  # pyright: ignore[reportArgumentType]
        )
    ).one()
