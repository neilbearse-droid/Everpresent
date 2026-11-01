"""A run killed mid-dispatch keeps every answer it paid for, and Resume
finishes it by asking only the cells it lacks."""

import pytest
from sqlmodel import select

from api.models import Result, ResultStatus, Run, RunStatus
from api.runs_service import _mark_abandoned, resume_run
from engine.retrievers.openai_api import RetrievalOutcome, parse_responses_payload
from tests.test_runs import (  # noqa: F401
    FIXTURE,
    NOSEARCH_PAYLOAD,
    _pending_run,
    job_env,
    make_tenant,
)
from tests.test_schedules import as_superadmin  # noqa: F401


class _Killed(BaseException):
    """Stands in for the SIGKILL a redeploy sends the worker: not an
    Exception, so the dispatcher's per-call handler can't file it as a
    failed answer; it tears the job down like the real thing."""


def _retrieve_that_dies_on(monkeypatch, call_no: int) -> dict:
    calls = {"n": 0}

    async def _fake(persona_prompt, query_text, *, api_key, model, timeout_s,
                    web_search=True, force_search=True):
        calls["n"] += 1
        if calls["n"] == call_no:
            raise _Killed()
        payload = FIXTURE if web_search else NOSEARCH_PAYLOAD
        return RetrievalOutcome(payload=payload, parsed=parse_responses_payload(payload),
                                latency_ms=42)

    monkeypatch.setattr("engine.retrievers.openai_api.retrieve", _fake)
    return calls


def test_killed_run_keeps_its_answers_and_resume_finishes_it(db_session, job_env,  # noqa: F811
                                                            monkeypatch):
    from api.config import get_settings
    from worker.jobs import run_mode_a

    monkeypatch.setattr(get_settings(), "openai_concurrency", 1)
    tenant = make_tenant(db_session)
    run_id = _pending_run(db_session, tenant)
    calls = _retrieve_that_dies_on(monkeypatch, call_no=3)
    with pytest.raises(_Killed):
        run_mode_a(run_id)

    run = db_session.get(Run, run_id)
    assert run is not None
    db_session.refresh(run)
    saved = db_session.exec(select(Result).where(Result.run_id == run_id)).all()
    # The two answers that came back before the kill are on disk, with their
    # cost booked; the worker simply died, so nothing marked the run.
    assert len(saved) == 2 and all(r.status == ResultStatus.ok and r.raw_uri for r in saved)
    assert run.counts["completed"] == 2 and run.cost_usd > 0
    assert run.counts["cost:openai_api"] == run.cost_usd
    assert run.status == RunStatus.running
    cost_after_kill = run.cost_usd

    # The watchdog files it as abandoned; the admin resumes it.
    _mark_abandoned(db_session, run)
    db_session.commit()
    monkeypatch.setattr("api.queue.enqueue_run", lambda rid: None)
    resume_run(db_session, run)
    db_session.refresh(run)
    assert run.status == RunStatus.pending and run.error is None
    assert run.counts["resumed"] == 1

    calls["n"] = -100  # never reaches the killing call again
    run_mode_a(run_id)
    db_session.refresh(run)
    assert run.status == RunStatus.complete and run.error is None
    results = db_session.exec(select(Result).where(Result.run_id == run_id)).all()
    cells = {(r.query_text, r.persona_name, str(r.variant)) for r in results}
    assert len(results) == 6 and len(cells) == 6  # no cell asked twice
    assert calls["n"] == -100 + 4  # only the four missing cells were asked
    assert run.counts["planned"] == 6 and run.counts["completed"] == 6
    assert run.counts["failed"] == 0 and run.counts["citations"] > 0
    assert run.cost_usd > cost_after_kill
    assert run.counts["cost:openai_api"] == run.cost_usd


def test_resume_is_only_for_failed_runs(client, as_superadmin, db_session, monkeypatch):  # noqa: F811
    tenant = make_tenant(db_session)
    run_id = _pending_run(db_session, tenant)
    run = db_session.get(Run, run_id)
    assert run is not None
    run.status = RunStatus.complete
    db_session.add(run)
    db_session.commit()
    assert client.post(f"/api/admin/runs/{run_id}/resume").status_code == 409

    run.status = RunStatus.failed
    run.error = "abandoned"
    db_session.add(run)
    db_session.commit()
    queued: list[int] = []
    monkeypatch.setattr("api.queue.enqueue_run", queued.append)
    resp = client.post(f"/api/admin/runs/{run_id}/resume")
    assert resp.status_code == 200 and resp.json()["status"] == "pending"
    assert queued == [run_id]
    assert client.post("/api/admin/runs/999999/resume").status_code == 404


def test_skip_done_matches_cells_one_answer_at_a_time():
    from worker.jobs import _skip_done

    work = [("q1", "A"), ("q1", "A"), ("q1", "A"), ("q2", "A")]
    kept, skipped = _skip_done(work, {("q1", "A"): 2}, key=lambda w: w)
    assert kept == [("q1", "A"), ("q2", "A")] and skipped == 2
