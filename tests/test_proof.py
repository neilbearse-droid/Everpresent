"""Proof of results: before/after vs control for shipped fixes."""

from datetime import UTC, date, datetime, timedelta

from api.models import (
    AgentTrafficDaily,
    AiReferralDaily,
    FirstPartyDaily,
    Intervention,
    Mention,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)

TODAY = date(2026, 10, 4)
SHIP = datetime(2026, 9, 6, tzinfo=UTC)
FIXED, OTHER = "best registrar for small business", "cheapest hosting"


def _answers(db, t, run, query, day, n, named):
    for i in range(n):
        r = Result(run_id=run.id, tenant_id=t.id, query_text=query, persona_name="generic",
                   surface=SurfaceCode.openai_api, variant=ResultVariant.search,
                   status=ResultStatus.ok,
                   created_at=datetime(day.year, day.month, day.day, 12, tzinfo=UTC))
        db.add(r)
        db.flush()
        if i < named:
            db.add(Mention(result_id=r.id, tenant_id=t.id, entity_type="brand",
                           entity_name="Acme", position=0, rank=1))


def _setup(db, after_named=18):
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add_all([Query(tenant_id=t.id, text=FIXED), Query(tenant_id=t.id, text=OTHER)])
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    before, after = SHIP.date() - timedelta(days=10), SHIP.date() + timedelta(days=10)
    _answers(db, t, run, FIXED, before, 30, 6)       # 20% before
    _answers(db, t, run, FIXED, after, 30, after_named)
    _answers(db, t, run, OTHER, before, 30, 9)       # control flat at 30%
    _answers(db, t, run, OTHER, after, 30, 9)
    db.add(Intervention(tenant_id=t.id, query_text=FIXED, description="New comparison page",
                        url="https://www.acme.com/compare/?utm=x", shipped_at=SHIP))
    for d, path, hits in [(before, "/compare", 10), (after, "/compare", 40),
                          (before, "/home", 100), (after, "/home", 100)]:
        db.add(AgentTrafficDaily(tenant_id=t.id, date=d.isoformat(), bot="GPTBot",
                                 purpose="search", path=path, status=200, hits=hits))
    db.add(AiReferralDaily(tenant_id=t.id, date=after.isoformat(), engine="ChatGPT",
                           sessions=50))
    db.add(FirstPartyDaily(tenant_id=t.id, source="gsc", date=after.isoformat(),
                           page="/other", metric="impressions", value=5))
    db.commit()
    return t


def test_page_path():
    from api.proof_service import page_path

    assert page_path("https://www.acme.com/compare/?utm=x") == "/compare"
    assert page_path("/compare/") == "/compare"
    assert page_path("") == ""


def test_real_lift_beats_control(db_session):
    from api.proof_service import intervention_proof

    t = _setup(db_session)
    d = intervention_proof(db_session, t.id, today=TODAY)
    it = d["items"][0]
    assert it["status"] == "proven" and it["window_days"] == 28
    m = {s["key"]: s for s in it["signals"]}
    assert m["mentions"]["before"] == 20.0 and m["mentions"]["after"] == 60.0
    assert m["mentions"]["control_delta_pts"] == 0.0 and m["mentions"]["net_pts"] == 40.0
    assert m["mentions"]["verdict"] == "up"
    assert m["ai_bot_reads"]["change_pct"] == 300.0
    assert m["ai_bot_reads"]["verdict"] == "up vs control"
    assert m["search_ai_impressions"]["verdict"] == "no data"
    assert m["referrals"]["kind"] == "context" and m["referrals"]["after"] == 50
    assert d["summary"].startswith("1 of 1 measured")


def test_no_lift_and_awaiting(db_session):
    from api.proof_service import intervention_proof

    t = _setup(db_session, after_named=7)
    it = intervention_proof(db_session, t.id, today=TODAY)["items"][0]
    assert it["status"] == "early"  # answers flat, bot reads up vs control
    soon = intervention_proof(db_session, t.id, today=SHIP.date() + timedelta(days=3))
    assert soon["items"][0]["status"] == "awaiting"
    assert soon["summary"].startswith("No fix has a full week")


def test_empty_ledger(db_session):
    from api.proof_service import intervention_proof

    t = Tenant(name="Acme", slug="acme")
    db_session.add(t)
    db_session.commit()
    assert intervention_proof(db_session, t.id)["items"] == []
