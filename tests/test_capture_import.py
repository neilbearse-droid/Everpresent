"""Vendor capture import: signed-in answers measured like our own."""

import json

import pytest
from sqlmodel import select

from api.models import (
    BrandProfile,
    Citation,
    Competitor,
    Mention,
    Result,
    Run,
    SponsoredUnit,
    Tenant,
    User,
)

HTML = """<div><p>GoDaddy and Namecheap are both solid. <a href="https://www.namecheap.com/x">NC</a></p>
<div class="x"><span>Sponsored</span><div><a href="https://wix.com/">Wix</a></div></div>
</div>"""

PAYLOAD = {
    "source": "Acme Panels",
    "captures": [
        {"surface": "chatgpt_web", "query": "best registrar?", "answer_html": HTML,
         "citations": [{"url": "https://www.godaddy.com/domains", "title": "GD"}],
         "captured_at": "2026-10-01T14:00:00Z", "logged_in": True, "model": "gpt-x"},
        {"surface": "perplexity_web", "query": "best registrar?",
         "answer": "Porkbun is cheapest.", "captured_at": "2026-10-01T14:05:00Z"},
    ],
}


@pytest.fixture()
def setup(db_session, client, login, monkeypatch, tmp_path):
    from api.config import get_settings

    # Raw envelopes go to a temp dir: CI runners can't write the default /data.
    monkeypatch.setattr(get_settings(), "raw_storage_dir", str(tmp_path))
    t = Tenant(name="GoDaddy", slug="gd")
    admin = User(email="a@x.test", clerk_user_id="u_a", is_superadmin=True)
    db_session.add_all([t, admin])
    db_session.commit()
    db_session.add(BrandProfile(tenant_id=t.id, brand_name="GoDaddy", domains=["godaddy.com"]))
    db_session.add_all([Competitor(tenant_id=t.id, name="Namecheap"),
                        Competitor(tenant_id=t.id, name="Porkbun"),
                        Competitor(tenant_id=t.id, name="Wix", domains=["wix.com"])])
    db_session.commit()
    login(admin)
    return t


def _post(client, body):
    return client.post("/api/admin/tenants/gd/import-captures", content=json.dumps(body),
                       headers={"Content-Type": "application/json"})


def test_import_measures_like_a_run(client, db_session, setup):
    r = _post(client, PAYLOAD)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2 and r.json()["skipped_duplicates"] == 0
    run = db_session.exec(select(Run)).one()
    assert run.trigger == "import" and run.counts["source"] == "Acme Panels"
    results = {str(x.surface): x for x in db_session.exec(select(Result)).all()}
    gpt = results["chatgpt_web"]
    assert gpt.logged_in is True and gpt.served_model == "gpt-x"
    assert gpt.created_at.date().isoformat() == "2026-10-01"
    urls = {c.url for c in db_session.exec(select(Citation)).all()}
    assert urls == {"https://www.namecheap.com/x", "https://www.godaddy.com/domains"}
    names = {m.entity_name for m in db_session.exec(select(Mention)).all()}
    assert {"GoDaddy", "Namecheap", "Porkbun"} <= names and "Wix" not in names
    assert db_session.exec(select(SponsoredUnit)).one().advertiser == "Wix"


def test_reimport_skips_duplicates(client, db_session, setup):
    assert _post(client, PAYLOAD).json()["imported"] == 2
    again = _post(client, PAYLOAD).json()
    assert again["imported"] == 0 and again["skipped_duplicates"] == 2
    assert again["run_id"] is None
    assert len(db_session.exec(select(Run)).all()) == 1


@pytest.mark.parametrize("bad, msg", [
    ({"source": "x", "captures": [{"surface": "myspace", "query": "q", "answer": "a"}]},
     "surface"),
    ({"source": "x", "captures": [{"surface": "chatgpt_web", "query": "q", "answer": ""}]},
     "empty answer"),
    ({"source": "x", "captures": [{"surface": "chatgpt_web", "query": "q", "answer": "a",
                                   "captured_at": "2999-01-01T00:00:00Z"}]}, "future"),
    ({"source": "x", "captures": [{"surface": "chatgpt_web", "query": "q", "answer": "a",
                                   "citations": [{"url": "javascript:alert(1)"}]}]}, "http"),
    ({"source": "x", "captures": []}, "captures"),
])
def test_rejects_bad_input(client, db_session, setup, bad, msg):
    r = _post(client, bad)
    assert r.status_code == 422 and msg in r.text
    assert db_session.exec(select(Result)).all() == []


def test_not_json_and_not_admin(client, db_session, setup, login):
    r = client.post("/api/admin/tenants/gd/import-captures", content=b"{nope",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and "JSON" in r.text
    member = User(email="m@x.test", clerk_user_id="u_m")
    db_session.add(member)
    db_session.commit()
    login(member)
    assert _post(client, PAYLOAD).status_code == 403
