"""Add to plan: an action shown anywhere in the product can be put on the
recommendations list by hand, and regeneration leaves it alone."""

from sqlmodel import select

from api.models import BrandProfile, Membership, MembershipRole, Recommendation, Tenant, User
from api.recommendations_service import generate_recommendations


def _member(db):
    t = Tenant(name="Acme", slug="acme", clerk_org_id="org_acme")
    db.add(t)
    db.commit()
    db.add(BrandProfile(tenant_id=t.id, brand_name="Acme", domains=["acme.com"]))
    u = User(email="m@example.com", clerk_user_id="u_m")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(Membership(user_id=u.id, tenant_id=t.id, role=MembershipRole.member))
    db.commit()
    return t, u


def test_add_to_plan_upserts_and_survives_regeneration(db_session, client, login):
    t, u = _member(db_session)
    login(u, org_id="org_acme", org_role="org:member")
    body = {"gap_ref": "engine:openai_api", "title": "Get cited on ChatGPT",
            "action_text": "Publish a dated answer page.", "link": "/dashboard/engines"}
    r = client.post("/api/tenant/recommendations", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "in_progress"
    assert r.json()["branch"] == "manual"

    # Adding the same action again updates the one row.
    r2 = client.post("/api/tenant/recommendations", json={**body, "title": "Renamed"})
    assert r2.status_code == 201
    rows = db_session.exec(select(Recommendation).where(Recommendation.tenant_id == t.id)).all()
    assert len(rows) == 1 and rows[0].title == "Renamed"

    # Regeneration auto-resolves plays that no longer match a gap; not these.
    generate_recommendations(db_session, t)
    db_session.refresh(rows[0])
    assert rows[0].status == "in_progress"

    # It shows up in the list the dashboard reads.
    listed = client.get("/api/tenant/recommendations").json()
    assert any(x["gap_ref"] == "manual:engine:openai_api" for x in listed)
