"""Worker pipeline robustness: restarts don't fail live runs, queueing failures
never strand a run, and the DB engine is rebuilt in a forked process."""

from datetime import timedelta

from sqlmodel import select

from api.models import (
    Persona,
    Query,
    Result,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    TenantSurface,
    utcnow,
)


def test_reclaim_only_fails_stale_running_runs(db_session, monkeypatch):
    from worker.main import reclaim_orphaned_runs

    monkeypatch.setattr("api.db.get_engine", lambda: db_session.get_bind())
    t = Tenant(name="T", slug="t")
    db_session.add(t)
    db_session.commit()
    now = utcnow()
    fresh = Run(tenant_id=t.id, status=RunStatus.running, started_at=now - timedelta(minutes=20))
    stale = Run(tenant_id=t.id, status=RunStatus.running, started_at=now - timedelta(hours=6))
    db_session.add_all([fresh, stale])
    db_session.commit()

    reclaim_orphaned_runs()
    db_session.expire_all()
    assert db_session.get(Run, fresh.id).status == RunStatus.running  # type: ignore[union-attr]
    assert db_session.get(Run, stale.id).status == RunStatus.failed  # type: ignore[union-attr]


def test_trigger_run_records_a_queue_failure(db_session, monkeypatch):
    from api.runs_service import trigger_run

    t = Tenant(name="T", slug="t", ai_processing_approved=True, approved_surfaces=["openai_api"])
    db_session.add(t)
    db_session.commit()
    db_session.add(TenantSurface(tenant_id=t.id, code=SurfaceCode.openai_api, enabled=True))
    db_session.commit()

    def _boom(_run_id):
        raise ConnectionError("redis down")

    monkeypatch.setattr("api.queue.enqueue_run", _boom)
    run = trigger_run(db_session, t)
    assert run.status == RunStatus.failed
    assert "could not queue" in (run.error or "")


def test_mode_b_queue_failure_still_processes_mode_a(db_session, monkeypatch, tmp_path):
    from api.config import get_settings
    from engine.retrievers.openai_api import ParsedResponse, RetrievalOutcome
    from worker.jobs import run_mode_a

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("RAW_STORAGE_DIR", str(tmp_path / "raw"))
    get_settings.cache_clear()
    monkeypatch.setattr("worker.jobs.get_engine", lambda: db_session.get_bind())

    async def _fake(persona_prompt, query_text, **kw):
        return RetrievalOutcome(payload={}, parsed=ParsedResponse(text="Acme is good.", model="m"),
                                latency_ms=1)

    monkeypatch.setattr("engine.retrievers.openai_api.retrieve", _fake)

    def _boom(_run_id):
        raise ConnectionError("redis down")

    monkeypatch.setattr("worker.jobs.enqueue_run_mode_b", _boom)

    t = Tenant(name="Acme", slug="acme", ai_processing_approved=True)
    db_session.add(t)
    db_session.commit()
    db_session.add(Query(tenant_id=t.id, text="best?"))
    db_session.add(Persona(tenant_id=t.id, name="p", prompt_text="", segment_tag="generic"))
    run = Run(tenant_id=t.id, status=RunStatus.pending,
              surface_set=["openai_api", "copilot_web"], mode_set=["A", "B"])
    db_session.add(run)
    db_session.commit()

    run_mode_a(run.id)  # type: ignore[arg-type]
    get_settings.cache_clear()
    db_session.refresh(run)
    assert run.status == RunStatus.complete  # finalized, not stranded
    assert "could not queue the browser engines" in (run.error or "")
    assert run.counts.get("mentions", 0) >= 1  # Mode A results were processed
    assert db_session.exec(select(Result).where(Result.run_id == run.id)).all()


def test_engine_is_rebuilt_after_fork(monkeypatch):
    import api.db as db

    monkeypatch.setattr(db, "_engine", None)
    first = db.get_engine()
    assert db.get_engine() is first
    monkeypatch.setattr(db.os, "getpid", lambda: -1)  # pretend we're a forked child
    assert db.get_engine() is not first
