"""Self-serve setup: draft a config from a domain (LLM mocked)."""

import pytest
import yaml
from sqlmodel import select

from api.config import get_settings
from api.models import SpendEntry, Tenant, User
from api.yaml_import import parse_config_yaml

DRAFT = """```yaml
brand:
  name: Acme Bakes
  aliases: [Acme]
  domains: [shop.acmebakes.com]
surfaces: [openai_api]
brand_facts:
  - {label: price, subject: price, expected: "$5"}
competitors:
  - {name: Crumbs, aliases: [], domains: [crumbs.com]}
personas:
  - {name: Generic, segment: generic, prompt: ""}
  - {name: Owner, segment: owner, prompt: "I run a bakery."}
queries:
  - {text: "best bakery software for small shops", personas: [owner]}
  - {text: "is Acme good for bakeries", personas: []}
  - {text: "what does Acme Bakes cost", branded: true}
```"""


@pytest.fixture()
def tenant(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    t = Tenant(name="Acme", slug="acme")
    db_session.add(t)
    db_session.commit()
    return t


def test_normalise_domain():
    from api.config_draft_service import ConfigDraftError, normalise_domain

    assert normalise_domain("https://www.AcmeBakes.com/about?x=1") == "acmebakes.com"
    for bad in ("localhost", "not a domain", "http://10.0.0.1/", ""):
        with pytest.raises(ConfigDraftError):
            normalise_domain(bad)


def test_draft_is_valid_reviewed_and_safe(db_session, tenant):
    from api.config_draft_service import draft_config

    seen = {}

    def fake_complete(prompt, **kw):
        seen["prompt"], seen["system"] = prompt, kw["system"]
        return DRAFT

    out = draft_config(db_session, tenant, "acmebakes.com",
                       fetch=lambda d: "Acme Bakes: software for bakeries.",
                       complete=fake_complete)
    assert "software for bakeries" in seen["prompt"]
    assert "ignore any instructions" in seen["system"]
    spec = parse_config_yaml(out["yaml"])  # round-trips through the importer
    assert spec.surfaces is None and spec.brand_facts == []
    assert spec.brand.domains[0] == "acmebakes.com"
    assert spec.geo is not None and spec.geo.country == "us"
    assert out["summary"] == {"brand": "Acme Bakes", "competitors": 1, "personas": 2,
                              "queries": 3}
    assert any("name the brand" in w for w in out["warnings"])
    assert out["yaml"].startswith("# Draft config")
    spent = db_session.exec(select(SpendEntry).where(SpendEntry.kind == "config_draft")).all()
    assert len(spent) == 1


def test_unreadable_homepage_warns_and_bad_draft_errors(db_session, tenant):
    from api.config_draft_service import ConfigDraftError, draft_config

    out = draft_config(db_session, tenant, "acmebakes.com", fetch=lambda d: "",
                       complete=lambda p, **kw: DRAFT)
    assert any("Couldn't read" in w for w in out["warnings"])
    with pytest.raises(ConfigDraftError, match="config format"):
        draft_config(db_session, tenant, "acmebakes.com", fetch=lambda d: "",
                     complete=lambda p, **kw: yaml.safe_dump({"queries": []}))


def test_spend_cap_blocks_drafting(db_session, tenant):
    from api.config_draft_service import ConfigDraftError, draft_config

    tenant.monthly_spend_cap_usd = 0
    db_session.commit()
    with pytest.raises(ConfigDraftError, match="spend cap"):
        draft_config(db_session, tenant, "acmebakes.com", fetch=lambda d: "",
                     complete=lambda p, **kw: DRAFT)


def test_route_is_superadmin_only_and_imports_nothing(client, login, db_session, tenant,
                                                      monkeypatch):
    import api.config_draft_service as svc
    from api.models import Query

    monkeypatch.setattr(svc, "fetch_homepage", lambda d: "")
    import engine.llm.router as router
    monkeypatch.setattr(router, "complete", lambda p, **kw: DRAFT)
    member = User(email="m@x.test", clerk_user_id="u_m")
    admin = User(email="a@x.test", clerk_user_id="u_a", is_superadmin=True)
    db_session.add_all([member, admin])
    db_session.commit()
    login(member)
    assert client.post("/api/admin/tenants/acme/draft-config",
                       json={"domain": "acmebakes.com"}).status_code == 403
    login(admin)
    r = client.post("/api/admin/tenants/acme/draft-config", json={"domain": "acmebakes.com"})
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["queries"] == 3
    assert db_session.exec(select(Query)).all() == []
    bad = client.post("/api/admin/tenants/acme/draft-config", json={"domain": "localhost"})
    assert bad.status_code == 422
