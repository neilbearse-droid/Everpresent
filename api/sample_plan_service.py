"""Sample-size planner: with the current question set, engines and schedule,
what size of change can we actually see, and when?

The headline mention rate compares the two halves of a 28-day window, so
the question is: how many answers per engine land in 14 days, and is that
enough to call a 10-point move real (two-sided 5% test, 80% power)? The
answer replaces a page of "not enough data yet" with a date."""

from datetime import UTC, datetime, timedelta
from typing import Any

from croniter import croniter
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel import Session, col, select

from api.models import Result, ResultStatus, ResultVariant, Run, RunSchedule, RunStatus
from engine.processing.stats import answers_needed, detectable_change

TARGET_CHANGE = 0.10  # a 10-point move in mention rate
HALF_WINDOW_DAYS = 14
LOOKBACK_RUNS = 3


def _runs_per_week(session: Session, tenant_id: int) -> float:
    sched = session.exec(select(RunSchedule).where(RunSchedule.tenant_id == tenant_id)).first()
    if sched is None or not sched.enabled or not sched.cron_expr:
        return 0.0
    try:
        it = croniter(sched.cron_expr, datetime(2026, 1, 5, tzinfo=UTC))  # a Monday
    except (ValueError, KeyError):
        return 0.0
    end = datetime(2026, 1, 12, tzinfo=UTC)
    n = 0
    while it.get_next(datetime) < end and n < 1000:
        n += 1
    return float(n)


def sample_plan(session: Session, tenant_id: int) -> dict[str, Any]:
    from api.dashboards_service import _branded_query_texts, _surface_label, mention_rates

    runs = session.exec(
        select(Run).where(Run.tenant_id == tenant_id,
                          col(Run.status).in_([RunStatus.complete, RunStatus.capped]))
        .order_by(col(Run.id).desc()).limit(LOOKBACK_RUNS)
    ).all()
    run_ids = [r.id for r in runs if r.id is not None]
    branded = _branded_query_texts(session, tenant_id)
    per_run: dict[str, float] = {}
    if run_ids:
        conds: list[Any] = [col(Result.run_id).in_(run_ids), Result.variant == ResultVariant.search,
                            Result.status == ResultStatus.ok]
        if branded:
            conds.append(col(Result.query_text).not_in(branded))
        for surface, n in session.execute(
            sa_select(col(Result.surface), func.count()).where(*conds)
            .group_by(col(Result.surface))
        ).all():
            per_run[str(surface)] = n / len(run_ids)

    rpw = _runs_per_week(session, tenant_id)
    rates = {e["surface"]: e for e in mention_rates(session, tenant_id).get("engines", [])}
    first = session.exec(
        select(func.min(Run.created_at)).where(Run.tenant_id == tenant_id)
    ).one()
    now = datetime.now(UTC)
    out = []
    for surface in sorted(set(per_run) | set(rates), key=_surface_label):
        r = rates.get(surface, {})
        p = (r.get("rate") or 30.0) / 100
        apr = round(per_run.get(surface, 0.0), 1)
        need = answers_needed(p, TARGET_CHANGE)  # per half-window
        per_half = apr * rpw * HALF_WINDOW_DAYS / 7
        can_see_now = detectable_change(p, int(per_half)) if per_half else None
        # The comparison window is a fixed 28 days, so waiting doesn't help if
        # each half is too small: the answers per half-window must grow.
        can = per_half >= need
        ready_by = None
        if can:
            start = first if first is not None else now
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            ready_by = max(start + timedelta(days=2 * HALF_WINDOW_DAYS), now).date().isoformat()
        multiplier = round(need / per_half, 1) if per_half and not can else None
        out.append({
            "surface": surface, "label": _surface_label(surface),
            "baseline_rate": round(100 * p, 1),
            "answers_per_run": apr,
            "answers_per_half_window": round(per_half),
            "needed_per_half_window": need,
            "detectable_change_pts": can_see_now,
            "can_detect_target": can,
            "ready_by": ready_by,
            "more_answers_needed_x": multiplier,
        })
    detectable = [e["detectable_change_pts"] for e in out if e["detectable_change_pts"]]
    return {
        "runs_per_week": rpw,
        "target_change_pts": round(100 * TARGET_CHANGE),
        "window_days": 2 * HALF_WINDOW_DAYS,
        "engines": out,
        "summary": _summary(out, rpw, detectable),
    }


def _summary(engines: list[dict], rpw: float, detectable: list[float]) -> str:
    if not engines:
        return "Run the first measurement to size the sample."
    if not rpw:
        return ("No schedule is set, so the data won't grow on its own. A 3x/week schedule is "
                "the usual starting point.")
    ok = [e for e in engines if e["can_detect_target"]]
    if len(ok) == len(engines):
        last = max((e["ready_by"] for e in engines if e["ready_by"]), default=None)
        return ("Every engine collects enough answers to call a 10-point move real"
                + (f" from {last}." if last else "."))
    best = min(detectable) if detectable else None
    short = [e for e in engines if not e["can_detect_target"]]
    text = (f"{len(ok)} of {len(engines)} engines collect enough answers in two weeks to call "
            "a 10-point move real.")
    if best:
        text += f" Today the smallest reliable change is about {best:.0f} points."
    worst = max(short, key=lambda e: e["more_answers_needed_x"] or 0)
    if worst["more_answers_needed_x"]:
        text += (f" {worst['label']} needs about {worst['more_answers_needed_x']}x more answers "
                 "per two weeks.")
    text += (" Ways to get there: more repeats per question or more runs per week (plan "
             "settings), or fewer, sharper questions.")
    return text
