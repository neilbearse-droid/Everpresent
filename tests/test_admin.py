from pathlib import Path

import pytest
from sqlmodel import select

from api.models import AuditLog, Persona, Query, Tenant, User

SEEDS = Path(__file__).resolve().parent.parent / "seeds"


@pytest.fixture()
def superadmin(db_session):
    user = User(email="neil@example.com", clerk_user_id="user_sa", is_superadmin=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def as_superadmin(login, superadmin):
    login(superadmin)
    return superadmin


def _create_tenant(client, slug="smith", name="Smith School of Business"):
    resp = client.post("/api/admin/tenants", json={"name": name, "slug": slug})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_and_list_tenants(client, as_superadmin):
    _create_tenant(client)
    resp = client.get("/api/admin/tenants")
    assert [t["slug"] for t in resp.json()] == ["smith"]


def test_duplicate_slug_rejected(client, as_superadmin):
    _create_tenant(client)
    resp = client.post("/api/admin/tenants", json={"name": "Again", "slug": "smith"})
    assert resp.status_code == 409


def test_yaml_import_and_reimport_replaces(client, as_superadmin, db_session):
    _create_tenant(client)
    yaml_text = (SEEDS / "smith.yaml").read_text()

    resp = client.post("/api/admin/tenants/smith/import-yaml", content=yaml_text)
    assert resp.status_code == 200, resp.text
    counts = resp.json()["imported"]
    assert counts["personas"] >= 3 and counts["queries"] >= 8

    # Replace semantics: re-import yields identical row counts, not doubles.
    resp = client.post("/api/admin/tenants/smith/import-yaml", content=yaml_text)
    assert resp.status_code == 200
    tenant = db_session.exec(select(Tenant).where(Tenant.slug == "smith")).one()
    personas = db_session.exec(select(Persona).where(Persona.tenant_id == tenant.id)).all()
    queries = db_session.exec(select(Query).where(Query.tenant_id == tenant.id)).all()
    assert len(personas) == counts["personas"]
    assert len(queries) == counts["queries"]

    detail = client.get("/api/admin/tenants/smith").json()
    assert detail["brand_profile"]["brand_name"] == "Smith School of Business"
    assert len(detail["surfaces"]) == 5  # full catalog, enabled flags per YAML


def test_invalid_yaml_rejected(client, as_superadmin):
    _create_tenant(client)
    resp = client.post("/api/admin/tenants/smith/import-yaml", content="queries: [oops")
    assert resp.status_code == 422
    resp = client.post("/api/admin/tenants/smith/import-yaml", content="no_brand: true")
    assert resp.status_code == 422


def test_governance_rejects_non_allowlisted_utility_model(client, as_superadmin):
    _create_tenant(client)
    resp = client.patch(
        "/api/admin/tenants/smith",
        json={"approved_utility_models": ["claude-fable-5"]},
    )
    assert resp.status_code == 422

    resp = client.patch(
        "/api/admin/tenants/smith",
        json={"approved_utility_models": ["claude-haiku-4-5-20251001"]},
    )
    assert resp.status_code == 200
    assert resp.json()["approved_utility_models"] == ["claude-haiku-4-5-20251001"]


def test_governance_flag_and_org_link(client, as_superadmin):
    _create_tenant(client)
    resp = client.patch(
        "/api/admin/tenants/smith",
        json={"ai_processing_approved": True, "clerk_org_id": "org_smith"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ai_processing_approved"] is True
    assert body["clerk_org_id"] == "org_smith"


def test_surface_toggle(client, as_superadmin):
    _create_tenant(client)
    resp = client.patch(
        "/api/admin/tenants/smith/surfaces",
        json={"code": "perplexity_web", "enabled": True},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True


def test_surface_toggle_syncs_governance_approval(client, as_superadmin):
    """Enabling a surface also adds it to approved_surfaces so a run is
    dispatchable from the single toggle; disabling removes the approval."""
    _create_tenant(client)
    client.patch(
        "/api/admin/tenants/smith/surfaces", json={"code": "openai_api", "enabled": True}
    )
    detail = client.get("/api/admin/tenants/smith").json()
    assert "openai_api" in detail["tenant"]["approved_surfaces"]

    client.patch(
        "/api/admin/tenants/smith/surfaces", json={"code": "openai_api", "enabled": False}
    )
    detail = client.get("/api/admin/tenants/smith").json()
    assert "openai_api" not in detail["tenant"]["approved_surfaces"]


def test_admin_mutations_are_audited(client, as_superadmin, db_session):
    _create_tenant(client)
    client.patch("/api/admin/tenants/smith", json={"ai_processing_approved": True})
    actions = [a.action for a in db_session.exec(select(AuditLog)).all()]
    assert any(a.startswith("tenant.create") for a in actions)
    assert any("ai_processing_approved" in a for a in actions)
