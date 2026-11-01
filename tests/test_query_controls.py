"""Clients pause questions and choose personas; reporting stops honestly."""

from datetime import timedelta

import pytest

from api.dashboards.common import _off_score_query_texts
from api.dashboards.overview import engine_breaks
from api.dashboards.queries import queries_intel
from api.models import Persona, Query, Tenant, User, utcnow
from api.query_controls import (
    QueryControlError,
    persona_access,
    set_query_active,
    set_query_personas,
)


def _tenant(db, plan="diagnose"):
    t = Tenant(name="Acme", slug="acme", plan=plan)
    db.add(t)
    db.commit()
    assert t.id is not None
    db.add_all([
        Persona(tenant_id=t.id, name="Generic", prompt_text="", segment_tag="generic"),
        Persona(tenant_id=t.id, name="Founder", prompt_text="I run a startup.",
                segment_tag="founder"),
        Persona(tenant_id=t.id, name="Agency", prompt_text="I run an agency.",
                segment_tag="agency"),
        Query(tenant_id=t.id, text="best crm"),
        Query(tenant_id=t.id, text="cheapest crm"),
        Query(tenant_id=t.id, text="Is Acme good?", branded=True),
    ])
    db.commit()
    return t


def _query(db, t, text):
    from sqlmodel import select
    return db.exec(select(Query).where(Query.tenant_id == t.id, Query.text == text)).one()


def test_pause_leaves_the_rates_and_keeps_the_history(db_session):
    t = _tenant(db_session)
    q = _query(db_session, t, "cheapest crm")
    set_query_active(db_session, t, q, False, by="client")
    db_session.commit()
    assert q.active is False and q.paused_at is not None and q.paused_by == "client"
    assert "cheapest crm" in _off_score_query_texts(db_session, t.id)
    row = next(r for r in queries_intel(db_session, t.id)["queries"] if r["id"] == q.id)
    assert row["active"] is False and row["paused_by"] == "client" and row["paused_at"]
    # Resuming clears the pause.
    set_query_active(db_session, t, q, True, by="client")
    db_session.commit()
    assert q.active and q.paused_at is None and q.paused_by is None
    assert "cheapest crm" not in _off_score_query_texts(db_session, t.id)


def test_the_last_competitive_question_cannot_be_paused(db_session):
    t = _tenant(db_session)
    set_query_active(db_session, t, _query(db_session, t, "cheapest crm"), False, by="client")
    db_session.commit()
    with pytest.raises(QueryControlError, match="at least one active"):
        set_query_active(db_session, t, _query(db_session, t, "best crm"), False, by="client")


def test_personas_are_gated_by_plan(db_session):
    t = _tenant(db_session, plan="monitor")  # one persona: the baseline only
    access = persona_access(db_session, t)
    assert access["selective"] and [p["in_plan"] for p in access["personas"]] == [False, False]
    assert access["unlock_plan"] == "Command"
    q = _query(db_session, t, "best crm")
    with pytest.raises(QueryControlError, match="not on the Monitor plan; available on Command"):
        set_query_personas(db_session, t, q, ["founder"])

    t.plan = "command"
    db_session.add(t)
    db_session.commit()
    assert persona_access(db_session, t)["unlock_plan"] is None
    q.persona_runs = [{"segment": "founder", "overlay": "for a SaaS startup"}]
    set_query_personas(db_session, t, q, ["agency", "founder", "generic"])
    db_session.commit()
    # Kept segments keep their overlay; the baseline is never listed twice.
    assert q.persona_runs == [{"segment": "agency", "overlay": ""},
                              {"segment": "founder", "overlay": "for a SaaS startup"}]
    with pytest.raises(QueryControlError, match="Unknown persona"):
        set_query_personas(db_session, t, q, ["nobody"])


def test_set_changes_are_a_note_on_the_pooled_line(db_session, monkeypatch):
    import api.dashboards.overview as overview_mod

    monkeypatch.setattr(overview_mod, "SERIES_BREAKS", [])
    monkeypatch.setattr(overview_mod, "_GEO_SERIES_BREAKS", [])
    t = _tenant(db_session)
    q = _query(db_session, t, "cheapest crm")
    q.active = False
    q.paused_at = utcnow() - timedelta(days=3)
    q.paused_by = "client"
    db_session.add(q)
    db_session.commit()
    lo = (utcnow() - timedelta(days=28)).date().isoformat()
    hi = utcnow().date().isoformat()
    notes = [n for n in engine_breaks(db_session, t.id, lo, hi) if n["surface"] == "overall"]
    assert len(notes) == 1 and notes[0]["note"].startswith("1 question paused on")
    # The onboarding day (every question created at once) is not a change.
    assert "added" not in notes[0]["note"]


def test_client_route_patches_its_own_questions(client, login, db_session):
    t = _tenant(db_session)
    t.clerk_org_id = "org_acme"
    db_session.add(t)
    user = User(email="m@example.com", clerk_user_id="u_m")
    db_session.add(user)
    db_session.commit()
    login(user, org_id="org_acme")
    q = _query(db_session, t, "cheapest crm")

    ctl = client.get("/api/tenant/query-controls").json()
    assert ctl["plan"] == "Diagnose" and [p["segment"] for p in ctl["personas"]] == [
        "founder", "agency"]
    assert [p["in_plan"] for p in ctl["personas"]] == [True, False]

    resp = client.patch(f"/api/tenant/queries/{q.id}", json={"active": False})
    assert resp.status_code == 200 and resp.json()["active"] is False
    assert resp.json()["paused_by"] == "client"
    bad = client.patch(f"/api/tenant/queries/{q.id}", json={"persona_segments": ["agency"]})
    assert bad.status_code == 422 and "Command" in bad.json()["detail"]
    ok = client.patch(f"/api/tenant/queries/{q.id}", json={"persona_segments": ["founder"]})
    assert ok.status_code == 200 and ok.json()["persona_runs"] == [
        {"segment": "founder", "overlay": ""}]
    # Another tenant's question is not reachable.
    other = Tenant(name="B", slug="b")
    db_session.add(other)
    db_session.commit()
    db_session.add(Query(tenant_id=other.id, text="x"))
    db_session.commit()
    foreign = _query(db_session, other, "x")
    denied = client.patch(f"/api/tenant/queries/{foreign.id}", json={"active": False})
    assert denied.status_code == 404
