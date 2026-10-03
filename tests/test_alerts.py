"""'What changed' alerts: only real moves, lost citations, and wrong facts."""

from datetime import timedelta

from sqlmodel import select

from api.dashboards_service import alerts
from api.models import (
    AccuracyFinding,
    BrandProfile,
    Mention,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunMode,
    SurfaceCode,
    Tenant,
    utcnow,
)


def _setup(db):
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    run = Run(tenant_id=t.id)
    db.add(run)
    db.commit()
    return t, run


def _answers(db, t, run, days_ago, n, named):
    for i in range(n):
        r = Result(run_id=run.id, tenant_id=t.id, query_text="best crm", persona_name="p",
                   persona_segment="all", surface=SurfaceCode.openai_api, mode=RunMode.A,
                   variant=ResultVariant.search, status=ResultStatus.ok,
                   created_at=utcnow() - timedelta(days=days_ago))
        db.add(r)
        db.commit()
        if i < named:
            db.add(Mention(result_id=r.id, tenant_id=t.id, entity_type="brand",
                           entity_name="Acme", position=0, rank=1))
    db.commit()


def test_a_real_drop_alerts_and_noise_does_not(db_session):
    t, run = _setup(db_session)
    _answers(db_session, t, run, 20, 60, named=42)  # 70%
    _answers(db_session, t, run, 3, 60, named=18)   # 30%
    got = alerts(db_session, t.id)
    assert got and got[0]["severity"] == "high" and got[0]["kind"] == "visibility_drop"
    assert "fell 40.0pt" in got[0]["text"]



def test_small_wobble_is_not_an_alert(db_session):
    t, run = _setup(db_session)
    _answers(db_session, t, run, 20, 60, named=30)  # 50%
    _answers(db_session, t, run, 3, 60, named=27)   # 45%
    assert [a for a in alerts(db_session, t.id) if a["kind"].startswith("visibility")] == []


def test_wrong_facts_in_latest_run_alert(db_session):
    t, run = _setup(db_session)
    _answers(db_session, t, run, 1, 2, named=2)
    r = db_session.exec(select(Result)).first()
    assert r is not None
    db_session.add(AccuracyFinding(result_id=r.id, tenant_id=t.id, fact_id=1,
                                   subject="domain privacy", stated="free"))
    db_session.commit()
    kinds = [a for a in alerts(db_session, t.id) if a["kind"] == "accuracy"]
    assert kinds and "domain privacy" in kinds[0]["text"]
