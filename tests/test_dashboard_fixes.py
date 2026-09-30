"""Regression tests for dashboard number fixes found in the pre-demo sweep."""

from api.dashboards_service import _date_window, aio_summary, overview
from api.models import (
    BrandProfile,
    QueryClassification,
    SurfaceCode,
    Tenant,
    VisibilityDaily,
)


def _tenant(db) -> int:
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    db.commit()
    return t.id  # type: ignore[return-value]


def test_far_future_end_date_does_not_crash():
    lo, hi = _date_window("2026-01-01", "9999-12-31")
    assert lo is not None and hi is None


def test_aio_tile_counts_each_query_once(db_session):
    tid = _tenant(db_session)
    signals = {"cited_domains": ["acme.com"]}
    for surface in (SurfaceCode.openai_api, SurfaceCode.gemini_api, SurfaceCode.claude_api):
        db_session.add(QueryClassification(
            tenant_id=tid, query_text="q1", surface=surface, web_search_likelihood="likely",
            google_aio_triggered=True, google_aio_signals=signals,
        ))
    db_session.commit()
    aio = aio_summary(db_session, tid)
    assert aio["queries_measured"] == 1
    assert aio["queries_with_aio"] == 1
    assert aio["brand_cited_in_aio"] == 1


def test_movers_ignore_entities_missing_on_one_day(db_session):
    tid = _tenant(db_session)
    db_session.add(VisibilityDaily(
        tenant_id=tid, date="2026-09-29", surface=SurfaceCode.openai_api,
        persona_segment="all", brand_score=50.0, competitor_scores={"Wix": 40.0},
    ))
    db_session.add(VisibilityDaily(
        tenant_id=tid, date="2026-09-30", surface=SurfaceCode.openai_api,
        persona_segment="all", brand_score=55.0,
        competitor_scores={"Wix": 42.0, "NewCo": 70.0},  # NewCo added today
    ))
    db_session.commit()
    movers = overview(db_session, tid, start="2026-09-01", end="2026-09-30")["movers"]
    labels = {m["label"] for m in movers}
    assert "NewCo" not in labels  # not a +70 jump from nothing
    assert "Wix" in labels
