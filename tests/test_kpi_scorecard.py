"""KPI scorecard: prominence, prominence-weighted answer share, head-to-head,
sentiment, and stability — over hand-built ranked mentions."""

from api.dashboards_service import kpi_scorecard
from api.models import (
    Mention,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)


def _result(db, run_id, tid, qtext, surface="openai_api", variant="search"):
    r = Result(run_id=run_id, tenant_id=tid, query_text=qtext, persona_name="p",
               surface=SurfaceCode(surface), variant=ResultVariant(variant),
               status=ResultStatus.ok)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _m(db, rid, tid, etype, name, rank, sentiment="neutral", snippet="ctx"):
    db.add(Mention(result_id=rid, tenant_id=tid, entity_type=etype, entity_name=name,
                   position=rank, rank=rank, sentiment=sentiment, context_snippet=snippet))
    db.commit()


def _run(db, tid):
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    return run.id


def test_scorecard_metrics(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    run_id = _run(db_session, tid)

    # r1: brand leads (rank 1), rival Globex rank 2, positive framing.
    r1 = _result(db_session, run_id, tid, "q1")
    _m(db_session, r1.id, tid, "brand", "Acme", 1, sentiment="positive", snippet="Acme is the best")
    _m(db_session, r1.id, tid, "competitor", "Globex", 2)
    # r2: rival leads (rank 1), brand second (rank 2), negative framing.
    r2 = _result(db_session, run_id, tid, "q2")
    _m(db_session, r2.id, tid, "competitor", "Globex", 1)
    _m(db_session, r2.id, tid, "brand", "Acme", 2, sentiment="negative", snippet="Acme is limited")
    # r3: brand absent, rival present.
    r3 = _result(db_session, run_id, tid, "q3")
    _m(db_session, r3.id, tid, "competitor", "Globex", 1)

    card = kpi_scorecard(db_session, tid)

    p = card["prominence"]
    assert p["measured"] == 3 and p["present"] == 2
    assert p["presence_rate"] == round(100 * 2 / 3, 1)
    assert p["lead_rate"] == 50.0  # present in 2, led 1
    assert p["avg_rank"] == 1.5
    assert p["position_distribution"] == {"leads": 1, "second": 1, "third_plus": 0}

    # Answer share (1/rank weights): Acme 1/1 + 1/2 = 1.5; Globex 1/2 + 1/1 + 1/1 = 2.5. Total 4.
    assert card["answer_share"] == round(100 * 1.5 / 4.0, 1)  # 37.5
    top = {d["name"]: d["share"] for d in card["share_breakdown"]}
    assert top["Globex"] == round(100 * 2.5 / 4.0, 1)  # 62.5

    # Head-to-head vs Globex: shared in r1 (brand rank1 < 2 -> win) and r2 (2 < 1 -> loss).
    h2h = {h["competitor"]: h for h in card["head_to_head"]}
    assert h2h["Globex"]["shared"] == 2 and h2h["Globex"]["wins"] == 1
    assert h2h["Globex"]["win_rate"] == 50.0

    assert card["sentiment"]["counts"] == {"positive": 1, "neutral": 0, "negative": 1}
    assert card["sentiment"]["examples"]["positive"][0]["query"] == "q1"


def test_stability_across_runs(db_session):
    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id

    # Run A: brand present in 1/1. Run B (newer): brand present in 0/1.
    run_a = _run(db_session, tid)
    ra = _result(db_session, run_a, tid, "q1")
    _m(db_session, ra.id, tid, "brand", "Acme", 1)
    run_b = _run(db_session, tid)
    _result(db_session, run_b, tid, "q1")  # no brand mention

    card = kpi_scorecard(db_session, tid)
    series = card["stability"]["series"]
    assert [s["presence_rate"] for s in series] == [100.0, 0.0]
    assert card["stability"]["swing"] == 100.0
    assert card["stability"]["label"] == "Volatile"
