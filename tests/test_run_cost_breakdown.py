"""Where a run's money went, per engine (admin run page)."""

from sqlmodel import select

from api.models import Result, Run
from api.runs_service import run_detail_payload
from tests.test_runs import _pending_run, fake_retrieve, job_env, make_tenant  # noqa: F401


def test_worker_books_cost_per_engine(db_session, job_env, fake_retrieve):  # noqa: F811
    from worker.jobs import run_mode_a

    tenant = make_tenant(db_session)
    run_id = _pending_run(db_session, tenant)
    run_mode_a(run_id)
    run = db_session.get(Run, run_id)
    assert run is not None
    assert run.counts["cost:openai_api"] > 0
    assert abs(run.counts["cost:openai_api"] - run.cost_usd) < 1e-6

    cost = run_detail_payload(db_session, run, with_cost=True)["cost_by_engine"]
    assert cost["source"] == "live" and cost["total_usd"] == round(run.cost_usd, 4)
    (engine,) = cost["engines"]
    assert engine["label"] == "ChatGPT" and engine["answers"] == 6
    assert engine["share_pct"] == 100.0 and cost["reprobe"] is None
    assert cost["unattributed_usd"] == 0.0
    # The client-facing payload never carries cost.
    assert "cost_by_engine" not in run_detail_payload(db_session, run)


def test_older_runs_are_summed_from_stored_answers_once(db_session, job_env,  # noqa: F811
                                                        fake_retrieve):  # noqa: F811
    from worker.jobs import run_mode_a

    tenant = make_tenant(db_session)
    run_id = _pending_run(db_session, tenant)
    run_mode_a(run_id)
    run = db_session.get(Run, run_id)
    assert run is not None
    # A run from before the counters existed.
    run.counts = {k: v for k, v in run.counts.items() if not k.startswith("cost:")}
    db_session.add(run)
    db_session.commit()

    cost = run_detail_payload(db_session, run, with_cost=True)["cost_by_engine"]
    assert cost["source"] == "stored answers"
    assert abs(cost["engines"][0]["cost_usd"] - run.cost_usd) < 1e-3
    # Written back, so the next read doesn't open every envelope again.
    db_session.refresh(run)
    assert run.counts["cost_breakdown_source"] == "envelopes"
    assert run_detail_payload(db_session, run, with_cost=True)["cost_by_engine"]["source"] == "live"
    assert db_session.exec(select(Result).where(Result.run_id == run_id)).first() is not None
