"""Landing-page waitlist (m40): the public form writes a row with a status,
a resubmission doesn't reset it, and only superadmins can read the list."""

import pytest
from sqlmodel import select

from api.models import User, WaitlistSignup, WaitlistStatus

SIGNUP = {
    "name": "Dana Okoro",
    "email": "Dana.Okoro@Example.com",
    "title": "VP Marketing",
    "company": "Northpeak",
    "industry": "SaaS / software",
}


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch):
    # The limiter talks to Redis; tests never do.
    monkeypatch.setattr("api.routes.waitlist._rate_limited", lambda request: False)


@pytest.fixture(autouse=True)
def no_email(monkeypatch):
    monkeypatch.setattr("api.waitlist_service.notify_signup", lambda *a, **k: False)
    monkeypatch.setattr("api.routes.waitlist.notify_signup", lambda *a, **k: False)


@pytest.fixture()
def superadmin(db_session, login):
    user = User(email="neil@example.com", clerk_user_id="user_sa", is_superadmin=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    login(user)
    return user


def test_signup_is_stored_with_new_status(client, db_session):
    resp = client.post("/api/waitlist", json={**SIGNUP, "source": "landing"})
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"status": "ok", "already_on_list": False}

    row = db_session.exec(select(WaitlistSignup)).one()
    assert row.email == "dana.okoro@example.com"  # lowercased identity
    assert row.name == "Dana Okoro"
    assert row.title == "VP Marketing"
    assert row.company == "Northpeak"
    assert row.industry == "SaaS / software"
    assert row.status == WaitlistStatus.new
    assert row.source == "landing"
    assert row.submissions == 1


def test_signup_needs_a_name_and_a_plausible_email(client):
    assert client.post("/api/waitlist", json={**SIGNUP, "name": "  "}).status_code == 422
    assert client.post("/api/waitlist", json={**SIGNUP, "email": "dana@"}).status_code == 422
    assert client.post("/api/waitlist", json={**SIGNUP, "email": ""}).status_code == 422


def test_resubmission_updates_details_and_keeps_the_status(client, db_session):
    client.post("/api/waitlist", json=SIGNUP)
    row = db_session.exec(select(WaitlistSignup)).one()
    row.status = WaitlistStatus.invited
    db_session.add(row)
    db_session.commit()

    resp = client.post(
        "/api/waitlist",
        json={**SIGNUP, "title": "CMO", "company": "", "utm": {"utm_source": "li"}},
    )
    assert resp.json() == {"status": "ok", "already_on_list": True}

    db_session.expire_all()
    row = db_session.exec(select(WaitlistSignup)).one()
    assert row.status == WaitlistStatus.invited  # not reset to new
    assert row.title == "CMO"
    assert row.company == "Northpeak"  # a blank resubmission doesn't wipe it
    assert row.utm == {"utm_source": "li"}
    assert row.submissions == 2


def test_honeypot_submission_writes_nothing(client, db_session):
    resp = client.post("/api/waitlist", json={**SIGNUP, "website": "http://spam.example"})
    assert resp.status_code == 201
    assert db_session.exec(select(WaitlistSignup)).all() == []


def test_long_fields_are_capped(client, db_session):
    client.post("/api/waitlist", json={**SIGNUP, "company": "N" * 500})
    row = db_session.exec(select(WaitlistSignup)).one()
    assert len(row.company) == 160


def test_industries_are_offered_publicly(client):
    resp = client.get("/api/waitlist/industries")
    assert resp.status_code == 200
    assert "Higher education" in resp.json()["industries"]


def test_list_is_superadmin_only(client, db_session):
    client.post("/api/waitlist", json=SIGNUP)
    assert client.get("/api/admin/waitlist").status_code in (401, 403)


def test_superadmin_reads_counts_and_moves_a_status(client, db_session, superadmin):
    client.post("/api/waitlist", json=SIGNUP)
    listing = client.get("/api/admin/waitlist")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["counts"]["new"] == 1
    assert body["counts"]["total"] == 1
    signup_id = body["signups"][0]["id"]

    patched = client.patch(
        f"/api/admin/waitlist/{signup_id}", json={"status": "invited", "note": "Sent Monday"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "invited"
    assert patched.json()["note"] == "Sent Monday"

    assert client.patch(
        f"/api/admin/waitlist/{signup_id}", json={"status": "nonsense"}
    ).status_code == 422

    filtered = client.get("/api/admin/waitlist?status=invited").json()
    assert [s["email"] for s in filtered["signups"]] == ["dana.okoro@example.com"]


def test_csv_export_neutralises_formulas(client, superadmin):
    client.post("/api/waitlist", json={**SIGNUP, "company": "=cmd()"})
    resp = client.get("/api/admin/waitlist.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "'=cmd()" in resp.text
    assert "dana.okoro@example.com" in resp.text
