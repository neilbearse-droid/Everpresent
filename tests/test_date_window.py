"""GA4-style date-range filtering on the dashboard reads: an explicit
[start, end] window restricts which results/rollups each view sees, and the
'latest state' views become 'state as of the end of the range'."""

from datetime import UTC, datetime

from api.dashboards_service import engine_scorecard, outcome, overview
from api.models import (
    AiReferralDaily,
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


def _tenant(db) -> int:
    tenant = Tenant(name="Acme", slug="acme")
    db.add(tenant)
    db.commit()
    return tenant.id


def _result(db, tid, qtext, created, *, brand: bool) -> Result:
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    r = Result(
        run_id=run.id, tenant_id=tid, query_text=qtext, persona_name="p",
        surface=SurfaceCode.openai_api, variant=ResultVariant.search,
        status=ResultStatus.ok, created_at=created,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    db.add(Mention(
        result_id=r.id, tenant_id=tid, entity_type="brand" if brand else "competitor",
        entity_name="Acme" if brand else "Globex", position=0, rank=1,
    ))
    db.commit()
    return r


def test_engine_scorecard_snapshot_as_of_range_end(db_session):
    """June run: brand absent. July run: brand visible. An end date inside June
    must show the June state, not today's."""
    tid = _tenant(db_session)
    db_session.add(Query(tenant_id=tid, text="q"))
    db_session.commit()

    _result(db_session, tid, "q", datetime(2026, 6, 10, tzinfo=UTC), brand=False)
    _result(db_session, tid, "q", datetime(2026, 7, 10, tzinfo=UTC), brand=True)

    now = engine_scorecard(db_session, tid)
    assert now["matrix"][0]["cells"]["openai_api"]["state"] == "brand"

    june = engine_scorecard(db_session, tid, start="2026-06-01", end="2026-06-30")
    assert june["matrix"][0]["cells"]["openai_api"]["state"] == "competitor"

    # A range with no data at all -> empty matrix cells, no crash.
    may = engine_scorecard(db_session, tid, start="2026-05-01", end="2026-05-31")
    assert may["matrix"][0]["cells"] == {}


def test_overview_trend_respects_range(db_session):
    tid = _tenant(db_session)
    for date, score in (("2026-06-01", 40.0), ("2026-06-15", 50.0), ("2026-07-01", 60.0)):
        db_session.add(VisibilityDaily(
            tenant_id=tid, date=date, surface=SurfaceCode.openai_api,
            persona_segment="all", brand_score=score,
        ))
    db_session.commit()

    windowed = overview(db_session, tid, start="2026-06-01", end="2026-06-30")
    assert [t["date"] for t in windowed["trend"]] == ["2026-06-01", "2026-06-15"]
    assert windowed["latest"]["date"] == "2026-06-15"
    # Movers compare the last two dates inside the window.
    brand_movers = [m for m in windowed["movers"] if m["kind"] == "brand_segment"]
    assert brand_movers[0]["before"] == 40.0
    assert brand_movers[0]["after"] == 50.0

    # Bad date input degrades to unfiltered, never errors.
    junk = overview(db_session, tid, start="not-a-date", end="also-junk")
    assert len(junk["trend"]) == 3


def test_outcome_range_keeps_connection_state(db_session):
    tid = _tenant(db_session)
    for date in ("2026-06-05", "2026-07-05"):
        db_session.add(AiReferralDaily(
            tenant_id=tid, date=date, engine="chatgpt", sessions=10, conversions=2,
        ))
    db_session.commit()

    windowed = outcome(db_session, tid, start="2026-07-01", end="2026-07-31")
    assert [s["date"] for s in windowed["series"]] == ["2026-07-05"]
    assert windowed["totals"]["sessions"] == 10
    # has_data reflects the account, not the window — the empty-range state
    # must not masquerade as 'GA4 not connected yet'.
    assert windowed["has_data"] is True
