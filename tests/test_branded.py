"""Branded-vs-competitive query split: branded queries are excluded from the
competitive-visibility metrics and surfaced in their own Brand-knowledge layer."""

from sqlmodel import select

from api.dashboards_service import (
    _branded_query_texts,
    _latest_results_by_variant,
    brand_report,
)
from api.models import (
    BrandProfile,
    Competitor,
    Mention,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    VisibilityDaily,
)


def _tenant(db):
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.add(Competitor(tenant_id=t.id, name="Rival", aliases=[], domains=["rival.com"]))
    db.add(Query(tenant_id=t.id, text="Acme review", branded=True))
    db.add(Query(tenant_id=t.id, text="best crm", branded=False))
    db.commit()
    return t.id


def _result(db, tid, qtext, *, run=None, seg="seg"):
    if run is None:
        run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
        db.add(run)
        db.commit()
        db.refresh(run)
    r = Result(run_id=run.id, tenant_id=tid, query_text=qtext, persona_name="p",
               persona_segment=seg, surface=SurfaceCode.openai_api,
               variant=ResultVariant.search, status=ResultStatus.ok)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r, run


def test_branded_query_texts(db_session):
    tid = _tenant(db_session)
    assert _branded_query_texts(db_session, tid) == frozenset({"Acme review"})


def test_scope_splits_results(db_session):
    tid = _tenant(db_session)
    _result(db_session, tid, "Acme review")
    _result(db_session, tid, "best crm")
    comp = _latest_results_by_variant(db_session, tid, ResultVariant.search, scope="competitive")
    branded = _latest_results_by_variant(db_session, tid, ResultVariant.search, scope="branded")
    everything = _latest_results_by_variant(db_session, tid, ResultVariant.search, scope="all")
    assert {q for (q, _s) in comp} == {"best crm"}
    assert {q for (q, _s) in branded} == {"Acme review"}
    assert {q for (q, _s) in everything} == {"Acme review", "best crm"}


def test_rollup_excludes_branded(db_session):
    from api.processing_service import _run_day, rollup_day

    tid = _tenant(db_session)
    _r1, run = _result(db_session, tid, "Acme review")
    _result(db_session, tid, "best crm", run=run)  # same run/day/surface/segment
    rollup_day(db_session, tid, _run_day(run))
    rows = db_session.exec(
        select(VisibilityDaily).where(VisibilityDaily.tenant_id == tid)
    ).all()
    # Both share (surface, segment, location) → one group; only the competitive
    # query counts, so result_count is 1, not 2.
    assert len(rows) == 1
    assert rows[0].extras["result_count"] == 1


def test_brand_report_presence_sentiment_accuracy(db_session):
    tid = _tenant(db_session)
    r, _run = _result(db_session, tid, "Acme review")
    db_session.add(Mention(
        result_id=r.id, tenant_id=tid, entity_type="brand", entity_name="Acme",
        position=0, rank=1, sentiment="positive", context_snippet="Acme is the top pick.",
    ))
    # A competitive query with no brand mention must NOT appear in the brand layer.
    _result(db_session, tid, "best crm")
    db_session.commit()

    rep = brand_report(db_session, tid)
    assert rep["observed"] is True
    assert rep["queries_tracked"] == 1
    assert rep["queries"][0]["query"] == "Acme review"
    assert rep["presence_rate"] == 100.0
    assert rep["sentiment"].get("positive") == 1
    assert rep["queries"][0]["surfaces"][0]["snippet"] == "Acme is the top pick."


def test_seed_marks_branded(db_session, client, login):
    # The GoDaddy seed flags Q3 (domain privacy) as branded.
    from pathlib import Path

    from api.models import User

    admin = User(email="neil@example.com", clerk_user_id="u_sa", is_superadmin=True)
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    login(admin)
    client.post("/api/admin/tenants", json={"name": "GoDaddy", "slug": "godaddy"})
    yaml_text = (Path(__file__).resolve().parent.parent / "seeds" / "godaddy.yaml").read_text()
    resp = client.post("/api/admin/tenants/godaddy/import-yaml", content=yaml_text)
    assert resp.status_code == 200, resp.text

    tenant = db_session.exec(select(Tenant).where(Tenant.slug == "godaddy")).one()
    branded = _branded_query_texts(db_session, tenant.id)
    assert "Is domain privacy free with GoDaddy?" in branded
