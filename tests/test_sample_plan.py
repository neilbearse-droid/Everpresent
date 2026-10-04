"""Sample-size planner: power math and the per-engine plan."""

from datetime import timedelta

from api.models import (
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunSchedule,
    RunStatus,
    SurfaceCode,
    Tenant,
    utcnow,
)
from engine.processing.stats import answers_needed, detectable_change


def test_power_math_matches_textbook_values():
    # 30% → 40% at 5%/80% needs ~356 per group (standard two-proportion table).
    assert 350 <= answers_needed(0.30, 0.10) <= 360
    assert answers_needed(0.30, 0.20) < answers_needed(0.30, 0.10)
    assert detectable_change(0.30, 356) == 10.0
    assert detectable_change(0.30, 10) is None  # below the minimum sample


def _setup(db, per_run_api: int, per_run_serp: int, schedule: str | None):
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    if schedule:
        db.add(RunSchedule(tenant_id=t.id, cron_expr=schedule, enabled=True))
    for k in range(3):
        run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete,
                  created_at=utcnow() - timedelta(days=40 - k))
        db.add(run)
        db.commit()
        for surface, n in ((SurfaceCode.openai_api, per_run_api),
                           (SurfaceCode.google_aio, per_run_serp)):
            for i in range(n):
                db.add(Result(run_id=run.id, tenant_id=t.id, query_text=f"q{i}",
                              persona_name="p", surface=surface, variant=ResultVariant.search,
                              status=ResultStatus.ok))
        db.commit()
    return t


def test_plan_flags_thin_engines_and_needs_a_schedule(db_session):
    from api.sample_plan_service import sample_plan

    t = _setup(db_session, per_run_api=150, per_run_serp=9, schedule="0 13 * * 1,3,5")
    plan = sample_plan(db_session, t.id)
    assert plan["runs_per_week"] == 3.0
    e = {x["surface"]: x for x in plan["engines"]}
    assert e["openai_api"]["can_detect_target"] and e["openai_api"]["ready_by"]
    assert not e["google_aio"]["can_detect_target"]
    assert e["google_aio"]["more_answers_needed_x"] > 5
    assert "Google AI Overviews needs about" in plan["summary"]


def test_plan_without_schedule(db_session):
    from api.sample_plan_service import sample_plan

    t = _setup(db_session, per_run_api=40, per_run_serp=0, schedule=None)
    plan = sample_plan(db_session, t.id)
    assert plan["runs_per_week"] == 0.0 and "No schedule" in plan["summary"]
