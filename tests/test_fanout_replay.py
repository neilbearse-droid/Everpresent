"""The fan-out simulator's replay data: real sub-searches, re-run results, answer."""

from sqlmodel import select

from api.config import get_settings
from api.models import Tenant


def test_replay_tells_the_bakery_story(db_session, monkeypatch, tmp_path, client, login):
    from api.dashboards.fanout import fanout_replay
    from api.demo_client import SLUG, build_demo_client
    from api.models import User

    monkeypatch.setattr(get_settings(), "raw_storage_dir", str(tmp_path))
    build_demo_client(db_session, "org_demo")
    tenant = db_session.exec(select(Tenant).where(Tenant.slug == SLUG)).one()
    assert tenant.id is not None

    data = fanout_replay(db_session, tenant.id)
    prompts = {p["query"]: p for p in data["prompts"]}
    bakery = prompts["Best website builder for a small bakery?"]
    chatgpt = next(e for e in bakery["engines"] if e["label"] == "ChatGPT")
    status = {s["text"]: s["status"] for s in chatgpt["subs"]}
    assert status["bakery website templates"] == "you"
    assert status["website builder with online ordering for a bakery"] == "rivals"
    assert status["how much does a small bakery website cost"] == "nobody"
    online = next(s for s in chatgpt["subs"] if "online ordering" in s["text"])
    assert online["winners"] == ["Siteforge"]

    # site: searches name whose site they searched; never a guessed "appear".
    sites = {s["site"]: s for s in chatgpt["subs"] if s["site"]}
    assert sites["siteforge.example"]["site_kind"] == "rival"
    assert sites["siteforge.example"]["site_name"] == "Siteforge"
    assert sites["northpeak.example"]["site_kind"] == "you"
    assert sites["northpeak.example"]["looked_for"] == "starter plan"
    assert sites["northpeak.example"]["status"] == "unchecked"

    # The answer half: who was named, and what was cited.
    assert chatgpt["named"] is True and chatgpt["rank"] == 2
    assert "Siteforge" in chatgpt["rivals_named"]
    kinds = {s["kind"] for s in chatgpt["sources"]}
    assert chatgpt["sources"] and kinds <= {"you", "rival", "other"}

    cheap = prompts["What's the cheapest way to get a domain and a website?"]
    assert all(not e["named"] for e in cheap["engines"])
    # Branded questions never appear here.
    assert all("Northpeak" not in q for q in prompts)

    # The route serves the same payload to the client's members.
    user = User(email="m@example.com", clerk_user_id="u_m")
    db_session.add(user)
    db_session.commit()
    login(user, org_id="org_demo")
    resp = client.get("/api/tenant/fanout-replay")
    assert resp.status_code == 200 and resp.json()["prompts"]


def test_replay_is_empty_without_fanout(db_session):
    from api.dashboards.fanout import fanout_replay

    t = Tenant(name="Empty", slug="empty")
    db_session.add(t)
    db_session.commit()
    assert t.id is not None
    assert fanout_replay(db_session, t.id)["prompts"] == []
