"""Headline metrics split by question topic."""

from sqlmodel import select

from api.config import get_settings
from api.models import Tenant


def test_topics_split_branded_agent_and_competitive(db_session, monkeypatch, tmp_path):
    from api.dashboards.measurement import kpi_scorecard, topic_scorecard
    from api.demo_client import SLUG, build_demo_client

    monkeypatch.setattr(get_settings(), "raw_storage_dir", str(tmp_path))
    build_demo_client(db_session)
    tenant = db_session.exec(select(Tenant).where(Tenant.slug == SLUG)).one()

    rows = {r["topic"]: r for r in topic_scorecard(db_session, tenant.id)}
    kinds = [r["kind"] for r in topic_scorecard(db_session, tenant.id)]
    assert kinds == sorted(kinds, key=["competitive", "agent", "branded"].index)

    branded = rows["About Northpeak"]
    assert branded["kind"] == "branded" and branded["rate"] > 95  # named by design
    assert branded["cited_rate"] > 0
    assert {"Agent tasks", "Agent coding"} <= rows.keys()
    assert rows["Agent tasks"]["kind"] == "agent"

    competitive = [r for r in rows.values() if r["kind"] == "competitive"]
    assert competitive and all(r["rate"] < 95 for r in competitive)
    for r in competitive:
        assert r["low"] <= r["rate"] <= r["high"] and r["questions"] >= 1

    # The scorecard carries the split; the headline stays branded-free.
    kpi = kpi_scorecard(db_session, tenant.id)
    assert kpi["by_topic"] and kpi["mention_rates"]["overall"]["rate"] < 95


def test_agent_prompts_stay_out_of_the_headline(db_session, monkeypatch, tmp_path):
    from api.dashboards.common import _off_score_query_texts
    from api.dashboards.measurement import mention_rates
    from api.demo_client import SLUG, build_demo_client
    from api.models import Query

    monkeypatch.setattr(get_settings(), "raw_storage_dir", str(tmp_path))
    build_demo_client(db_session)
    tenant = db_session.exec(select(Tenant).where(Tenant.slug == SLUG)).one()
    queries = db_session.exec(select(Query).where(Query.tenant_id == tenant.id)).all()
    agent = {q.text for q in queries if q.corpus_tag in ("agent_task", "agent_code")}
    branded = {q.text for q in queries if q.branded}
    assert agent and _off_score_query_texts(db_session, tenant.id) == frozenset(agent | branded)
    competitive = len([q for q in queries if q.text not in agent | branded])
    assert mention_rates(db_session, tenant.id)["overall"]["prompts"] == competitive
