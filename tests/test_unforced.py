"""'What users see': the unforced mention rate beside the forced one."""

from sqlmodel import select

from api.dashboards.measurement import mention_rates
from api.models import (
    BrandProfile,
    Mention,
    Query,
    Result,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)
from tests.test_runs import _pending_run, fake_retrieve, job_env, make_tenant  # noqa: F401


def _answers(db, tid, run_id, surface, variant, n, *, named, searched):
    for i in range(n):
        r = Result(run_id=run_id, tenant_id=tid, query_text=f"q{i % 3}", persona_name="p",
                   surface=surface, variant=variant,
                   web_search_calls=1 if i < searched else 0)
        db.add(r)
        db.commit()
        db.refresh(r)
        if i < named:
            db.add(Mention(result_id=r.id, tenant_id=tid, entity_type="brand",
                           entity_name="Acme", position=0, rank=1))
    db.commit()


def test_forced_engines_report_their_unforced_answers(db_session):
    t = Tenant(name="Acme", slug="acme")
    db_session.add(t)
    db_session.commit()
    assert t.id is not None
    db_session.add(BrandProfile(tenant_id=t.id, brand_name="Acme"))
    for i in range(3):
        db_session.add(Query(tenant_id=t.id, text=f"q{i}"))
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    assert run.id is not None

    # ChatGPT: forced answers name Acme 8/10; its unforced probe only 2/10,
    # and only 3 of those 10 searched.
    _answers(db_session, t.id, run.id, SurfaceCode.openai_api, ResultVariant.search, 10,
             named=8, searched=10)
    _answers(db_session, t.id, run.id, SurfaceCode.openai_api, ResultVariant.natural, 10,
             named=2, searched=3)
    # Claude isn't forced: its measured answer is already what users see.
    _answers(db_session, t.id, run.id, SurfaceCode.claude_api, ResultVariant.search, 10,
             named=5, searched=4)
    # The no-search twin never counts toward either rate.
    _answers(db_session, t.id, run.id, SurfaceCode.openai_api, ResultVariant.nosearch, 10,
             named=10, searched=0)

    m = mention_rates(db_session, t.id)
    by = {e["surface"]: e for e in m["engines"]}
    chatgpt, claude = by["openai_api"], by["claude_api"]
    assert chatgpt["forced"] and chatgpt["rate"] == 80.0
    assert chatgpt["unforced"]["rate"] == 20.0 and chatgpt["unforced"]["searched_rate"] == 30.0
    assert not claude["forced"] and claude["unforced"]["rate"] == claude["rate"] == 50.0
    assert claude["unforced"]["searched_rate"] == 40.0
    # Headline unchanged (forced ChatGPT + Claude); unforced pools probe + Claude.
    assert m["overall"]["rate"] == 65.0
    assert m["overall"]["unforced"]["rate"] == 35.0


def test_probe_rotates_through_every_question(db_session, job_env, fake_retrieve,  # noqa: F811
                                               monkeypatch):
    from api.config import get_settings
    from worker.jobs import run_mode_a

    monkeypatch.setenv("NATURAL_PROBE_FRACTION", "0.34")
    get_settings.cache_clear()
    tenant = make_tenant(db_session, queries=6, personas=1)
    probed: set[str] = set()
    for _ in range(3):
        run_id = _pending_run(db_session, tenant)
        run_mode_a(run_id)
        probed |= {r.query_text for r in db_session.exec(
            select(Result).where(Result.run_id == run_id,
                                 Result.variant == ResultVariant.natural)).all()}
    assert len(probed) == 6  # a third per run, a different third each time


def test_pooled_rate_waits_for_every_forced_engine(db_session):
    t = Tenant(name="Acme", slug="acme")
    db_session.add(t)
    db_session.commit()
    assert t.id is not None
    db_session.add(Query(tenant_id=t.id, text="q0"))
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    assert run.id is not None
    _answers(db_session, t.id, run.id, SurfaceCode.openai_api, ResultVariant.search, 4,
             named=4, searched=4)
    _answers(db_session, t.id, run.id, SurfaceCode.claude_api, ResultVariant.search, 4,
             named=1, searched=1)
    m = mention_rates(db_session, t.id)
    # Claude alone isn't "what users see": ChatGPT's unforced answers are missing.
    assert m["overall"]["unforced"] is None
    assert m["overall"]["unforced_missing"] == ["ChatGPT"]
