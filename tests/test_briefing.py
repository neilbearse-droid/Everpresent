"""Weekly briefing: verdict, reasons and this week's plays."""

from api.models import Recommendation, RecommendationStatus, Tenant


def _tenant(db):
    t = Tenant(name="Acme", slug="acme")
    db.add(t)
    db.commit()
    return t


def test_briefing_without_data(db_session):
    from api.briefing_service import briefing

    t = _tenant(db_session)
    b = briefing(db_session, t.id)
    assert b["winning"]["verdict"] == "unknown"
    assert b["this_week"] == [] and b["focus"] is None


def test_briefing_picks_top_open_plays_and_focus(db_session):
    from api.briefing_service import briefing

    t = _tenant(db_session)
    for ref, pr, status, branch in [
        ("a", 90, RecommendationStatus.open, "aio"),
        ("b", 70, RecommendationStatus.in_progress, "reviews"),
        ("c", 99, RecommendationStatus.done, "earned"),
        ("d", 60, RecommendationStatus.open, "owned"),
        ("e", 10, RecommendationStatus.open, "community"),
        ("s", 100, RecommendationStatus.open, "strategy"),
    ]:
        db_session.add(Recommendation(tenant_id=t.id, gap_ref=ref, branch=branch,
                                      action_text=f"do {ref}", title=f"Play {ref}",
                                      priority=pr, status=status, why=f"because {ref}"))
    db_session.commit()
    b = briefing(db_session, t.id)
    assert [p["title"] for p in b["this_week"]] == ["Play a", "Play b", "Play d"]
    assert b["this_week"][0]["why"] == "because a"
    assert b["focus"] == "Play s"


def test_briefing_route(client, login, db_session):
    from api.models import User

    t = Tenant(name="Acme", slug="acme", clerk_org_id="org_a")
    u = User(email="m@x.test", clerk_user_id="u_m")
    db_session.add_all([t, u])
    db_session.commit()
    login(u, org_id="org_a", org_role="org:member")
    r = client.get("/api/tenant/briefing")
    assert r.status_code == 200
    assert set(r.json()) >= {"winning", "why", "this_week", "focus"}
