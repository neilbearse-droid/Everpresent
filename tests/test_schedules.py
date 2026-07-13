"""M5 schedules: admin CRUD with cron validation, and the scheduler tick
firing due schedules with trigger='schedule'."""

from datetime import UTC, datetime

import pytest
from sqlmodel import select

from api.models import Run, RunSchedule, User
from tests.test_runs import enqueue_spy, make_tenant  # noqa: F401  (fixtures)
from worker.scheduler import tick


@pytest.fixture()
def as_superadmin(login, db_session):
    user = User(email="neil@example.com", clerk_user_id="user_sa", is_superadmin=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    login(user)
    return user


def test_put_schedule_validates_cron(client, as_superadmin, db_session):
    make_tenant(db_session)
    resp = client.put(
        "/api/admin/tenants/smith/schedule",
        json={"cron_expr": "not a cron", "enabled": True},
    )
    assert resp.status_code == 422

    resp = client.put(
        "/api/admin/tenants/smith/schedule",
        json={"cron_expr": "0 13 * * 1", "enabled": True},  # weekly, Monday 13:00 UTC
    )
    assert resp.status_code == 200
    assert resp.json()["cron_expr"] == "0 13 * * 1"

    # Update replaces, not duplicates, and re-arms.
    resp = client.put(
        "/api/admin/tenants/smith/schedule",
        json={"cron_expr": "0 9 * * 2", "enabled": False},
    )
    assert resp.status_code == 200
    schedules = db_session.exec(select(RunSchedule)).all()
    assert len(schedules) == 1
    assert schedules[0].enabled is False and schedules[0].next_run_at is None


def test_tick_arms_then_fires_due_schedule(db_session, enqueue_spy):  # noqa: F811
    tenant = make_tenant(db_session)
    assert tenant.id is not None
    db_session.add(RunSchedule(tenant_id=tenant.id, cron_expr="0 13 * * 1", enabled=True))
    db_session.commit()

    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)  # a Monday, before 13:00
    assert tick(db_session, now) == []  # first tick arms only
    schedule = db_session.exec(select(RunSchedule)).one()
    assert schedule.next_run_at is not None

    # Not due yet.
    assert tick(db_session, datetime(2026, 7, 13, 12, 59, tzinfo=UTC)) == []

    # Due: fires, advances to next Monday.
    fired = tick(db_session, datetime(2026, 7, 13, 13, 0, 30, tzinfo=UTC))
    assert len(fired) == 1
    run = db_session.get(Run, fired[0])
    assert run is not None and run.trigger == "schedule" and run.status == "pending"
    assert enqueue_spy == [run.id]
    db_session.refresh(schedule)
    next_at = schedule.next_run_at
    assert next_at is not None
    assert next_at.replace(tzinfo=UTC) == datetime(2026, 7, 20, 13, 0, tzinfo=UTC)

    # And doesn't double-fire within the same window.
    assert tick(db_session, datetime(2026, 7, 13, 13, 1, tzinfo=UTC)) == []


def test_disabled_schedule_never_fires(db_session, enqueue_spy):  # noqa: F811
    tenant = make_tenant(db_session)
    assert tenant.id is not None
    db_session.add(
        RunSchedule(
            tenant_id=tenant.id,
            cron_expr="* * * * *",
            enabled=False,
            next_run_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )
    db_session.commit()
    assert tick(db_session, datetime(2026, 7, 13, 13, 0, tzinfo=UTC)) == []
    assert enqueue_spy == []


def test_tick_enqueues_nightly_mirror_once(db_session, enqueue_spy, monkeypatch):  # noqa: F811
    from api.config import get_settings

    monkeypatch.setenv("BIGQUERY_PROJECT", "test-project")
    monkeypatch.setenv("MIRROR_HOUR_UTC", "9")
    get_settings.cache_clear()
    enqueued: list[tuple] = []

    class FakeQueue:
        def enqueue(self, *args, **kwargs):
            enqueued.append(args)

    monkeypatch.setattr("api.queue.get_queue", lambda name="default": FakeQueue())

    tick(db_session, datetime(2026, 7, 13, 9, 5, tzinfo=UTC))
    tick(db_session, datetime(2026, 7, 13, 10, 0, tzinfo=UTC))  # same day: no re-enqueue
    assert len(enqueued) == 1
    assert enqueued[0][0] == "worker.mirror.mirror_to_bigquery"

    tick(db_session, datetime(2026, 7, 14, 9, 5, tzinfo=UTC))  # next day: fires again
    assert len(enqueued) == 2
    get_settings.cache_clear()
