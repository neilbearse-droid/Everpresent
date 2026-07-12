"""Dashboard read APIs over processed data (M3 gate: visibility trend and
share-of-voice from live data)."""

import pytest
from sqlmodel import select

from api.models import User, VisibilityDaily
from tests.test_processing import configured_tenant  # noqa: F401
from tests.test_runs import (  # noqa: F401  (fixtures)
    _pending_run,
    fake_retrieve,
    job_env,
    make_tenant,
)


@pytest.fixture()
def member(db_session):
    user = User(email="member@smith.example", clerk_user_id="user_smith")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def processed_run(db_session, job_env, fake_retrieve, configured_tenant):  # noqa: F811
    from worker.jobs import run_mode_a

    run_id = _pending_run(db_session, configured_tenant)
    run_mode_a(run_id)
    return run_id


def test_overview(client, login, member, processed_run):
    login(member, org_id="org_smith")
    body = client.get("/api/tenant/overview").json()
    assert body["brand_name"] == "Smith School of Business"
    assert len(body["trend"]) == 1
    point = body["trend"][0]
    assert point["brand_score"] == pytest.approx(83.33, abs=0.01)
    assert point["competitors"]["Rotman School of Management"] == pytest.approx(85.0)
    # SOV: every result mentions all three entities equally.
    assert body["share_of_voice"] == {
        "Smith School of Business": pytest.approx(33.33, abs=0.01),
        "Rotman School of Management": pytest.approx(33.33, abs=0.01),
        "Ivey Business School": pytest.approx(33.33, abs=0.01),
    }
    assert body["movers"] == []  # single date, nothing to compare yet
    assert body["latest"]["brand_score"] == pytest.approx(83.33, abs=0.01)


def test_personas_breakdown(client, login, member, processed_run):
    login(member, org_id="org_smith")
    body = client.get("/api/tenant/personas-intel").json()
    assert [s["segment"] for s in body["segments"]] == ["seg0", "seg1"]
    for segment in body["segments"]:
        assert segment["brand_score"] == pytest.approx(83.33, abs=0.01)
        assert segment["mention_rate"] == 1.0
        assert segment["result_count"] == 2
        assert "Ivey Business School" in segment["competitor_scores"]
    assert len(body["trend"]) == 2  # one date × two segments


def test_queries_intel(client, login, member, processed_run):
    login(member, org_id="org_smith")
    body = client.get("/api/tenant/queries-intel").json()
    assert len(body["queries"]) == 2
    for q in body["queries"]:
        assert q["classification"]["web_search_likelihood"] == "very_likely"
        assert q["classification"]["signals"]["citation_count"] == 2
        latest = q["latest_results"]["openai_api"]
        assert latest["mode"] == "A"
        assert latest["brand_mentioned"] is True


def test_movers_after_second_day(client, login, member, processed_run, db_session):
    # Fake an earlier day (inside the trend window) with lower scores to
    # exercise the movers diff.
    from datetime import UTC, datetime, timedelta

    earlier = (datetime.now(UTC) - timedelta(days=5)).date().isoformat()
    rows = db_session.exec(select(VisibilityDaily)).all()
    for row in rows:
        db_session.add(
            VisibilityDaily(
                tenant_id=row.tenant_id,
                date=earlier,
                surface=row.surface,
                persona_segment=row.persona_segment,
                brand_score=row.brand_score - 10,
                competitor_scores={n: s + 5 for n, s in row.competitor_scores.items()},
                extras=row.extras,
                scorer_version=row.scorer_version,
            )
        )
    db_session.commit()
    login(member, org_id="org_smith")
    body = client.get("/api/tenant/overview").json()
    movers = {m["label"]: m for m in body["movers"]}
    assert movers["Brand · seg0"]["delta"] == pytest.approx(10.0, abs=0.01)
    assert movers["Rotman School of Management"]["delta"] == pytest.approx(-5.0, abs=0.01)


def test_dashboards_are_tenant_scoped(client, login, member, processed_run, db_session):
    make_tenant(db_session, "other", org="org_other", queries=1, personas=1)
    login(member, org_id="org_other")
    body = client.get("/api/tenant/overview").json()
    assert body["trend"] == [] and body["share_of_voice"] == {}
