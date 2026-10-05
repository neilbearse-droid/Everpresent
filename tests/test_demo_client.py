"""The fictional demo client: its playbook must match its data."""

import pytest
from sqlmodel import select

from api.config import get_settings
from api.models import (
    AgentTrafficDaily,
    PagePresence,
    Recommendation,
    RecommendationStatus,
    Tenant,
    User,
)


@pytest.fixture()
def demo(db_session, monkeypatch, tmp_path):
    from api.demo_client import SLUG, build_demo_client

    monkeypatch.setattr(get_settings(), "raw_storage_dir", str(tmp_path))
    out = build_demo_client(db_session)
    tenant = db_session.exec(select(Tenant).where(Tenant.slug == SLUG)).one()
    plays = {r.gap_ref: r for r in db_session.exec(select(Recommendation).where(
        Recommendation.tenant_id == tenant.id,
        Recommendation.status == RecommendationStatus.open)).all()}
    return out, tenant, plays


def test_every_story_beat_becomes_a_specific_play(demo):
    out, tenant, plays = demo
    assert out["answers"] > 500 and tenant.monthly_spend_cap_usd == 0
    acc = plays["accuracy:" + next(k.split(":")[1] for k in plays if k.startswith("accuracy:"))]
    assert "$19; it's $12" in acc.action_text
    assert "https://northpeak.example/help/plans" in acc.steps[0]
    assert "domainly.example" not in acc.steps[0]  # only pages that could carry the price
    assert "says Starter plan is $19" in plays["own_page:facts:/help/plans"].action_text
    assert "crawler:Claude-SearchBot:absent" in plays
    assert "crawler:PerplexityBot:errors" in plays
    assert "refresh:https://northpeak.example/blog/website-cost-guide" in plays
    assert "at_risk:/blog/website-cost-guide" in plays
    assert "/old-pricing" in plays["broken_pages"].action_text
    assert "/features/ecommerce" in plays["read_not_cited"].action_text
    assert "owned:chatgpt_docs" in plays and "sources:review" in plays
    assert any(k.startswith("model_change:openai_api:") for k in plays)
    web = next(p for k, p in plays.items() if k.endswith("::branch:web_search"))
    assert "Domainly and Siteforge" in web.action_text
    assert "cheapest website builder with a free domain" in web.steps[0]
    assert any(k.endswith("::branch:training") for k in plays)
    assert any(k.endswith("::branch:aio") for k in plays)


def test_no_play_gives_advice_the_data_does_not_support(demo):
    _, _, plays = demo
    # Pages only refused to one bot are an access problem, never "dead" or
    # "erroring" pages to redirect or fix.
    for blocked_only in ("/features/online-booking", "/pricing"):
        assert f"at_risk:{blocked_only}" not in plays
        assert blocked_only not in plays["broken_pages"].action_text
    # Don't ask to win back a citation for the page that states the wrong price.
    assert "refresh:https://northpeak.example/help/plans" not in plays
    assert "connect_logs" not in plays  # logs are present


def test_downstream_views_tell_the_same_story(demo, db_session):
    from api.ads_service import ads_report
    from api.agent_picks_service import agent_picks
    from api.proof_service import intervention_proof

    _, tenant, _ = demo
    proof = intervention_proof(db_session, tenant.id)["items"][0]
    assert proof["status"] == "proven"
    assert {s["key"]: s["verdict"] for s in proof["signals"]}["ai_bot_reads"] == "up vs control"
    assert agent_picks(db_session, tenant.id)["has_data"]
    ads = ads_report(db_session, tenant.id)
    assert ads["advertisers"][0]["name"] == "Siteforge"


def test_rebuild_replaces_only_the_demo(demo, db_session, monkeypatch, tmp_path):
    from api.demo_client import build_demo_client

    out, tenant, plays = demo
    other = Tenant(name="Real", slug="real")
    db_session.add(other)
    db_session.commit()
    db_session.add(AgentTrafficDaily(tenant_id=other.id, date="2026-10-01", bot="GPTBot",
                                     company="OpenAI", purpose="training", path="/", status=200,
                                     hits=5))
    db_session.commit()
    again = build_demo_client(db_session)
    assert again["answers"] == out["answers"] and again["open_plays"] == out["open_plays"]
    assert db_session.exec(select(AgentTrafficDaily).where(
        AgentTrafficDaily.tenant_id == other.id)).one().hits == 5


def test_nightly_crawl_leaves_the_seeded_pages_alone(demo, db_session, monkeypatch):
    from worker.page_crawl import crawl_power_pages

    monkeypatch.setattr("worker.page_crawl._engine", lambda: db_session.get_bind())
    _, tenant, _ = demo
    before = len(db_session.exec(select(PagePresence)).all())
    assert crawl_power_pages(tenant.id) == 0
    assert len(db_session.exec(select(PagePresence)).all()) == before


def test_endpoint_is_superadmin_only_and_queues(client, login, db_session, monkeypatch):
    calls = []
    monkeypatch.setattr("api.queue.enqueue_demo_client", lambda org: calls.append(org))
    member = User(email="m@x.test", clerk_user_id="u_m")
    admin = User(email="a@x.test", clerk_user_id="u_a", is_superadmin=True)
    db_session.add_all([member, admin])
    db_session.commit()
    login(member)
    assert client.post("/api/admin/demo-client", json={}).status_code == 403
    login(admin)
    assert client.post("/api/admin/demo-client", json={"clerk_org_id": "bad"}).status_code == 422
    r = client.post("/api/admin/demo-client", json={"clerk_org_id": "org_abc123XYZ"})
    assert r.status_code == 202 and calls == ["org_abc123XYZ"]
