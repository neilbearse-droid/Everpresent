"""Tenancy isolation (§5.1, §7.3): merge-blocking proof that a member of one
tenant cannot read another tenant's data through any route."""

import pytest
from sqlmodel import select

from api.models import Membership, MembershipRole, Query, Tenant, User


@pytest.fixture()
def two_tenants(db_session):
    a = Tenant(name="Tenant A", slug="tenant-a", clerk_org_id="org_a")
    b = Tenant(name="Tenant B", slug="tenant-b", clerk_org_id="org_b")
    db_session.add(a)
    db_session.add(b)
    db_session.commit()
    assert a.id is not None and b.id is not None
    db_session.add(Query(tenant_id=a.id, text="query for A", corpus_tag="core"))
    db_session.add(Query(tenant_id=b.id, text="query for B", corpus_tag="core"))
    db_session.commit()
    return a, b


@pytest.fixture()
def member_a(db_session):
    user = User(email="member@tenant-a.example", clerk_user_id="user_a")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_member_reads_only_own_tenant(client, login, two_tenants, member_a):
    login(member_a, org_id="org_a")
    resp = client.get("/api/tenant/queries")
    assert resp.status_code == 200
    texts = [q["text"] for q in resp.json()]
    assert texts == ["query for A"]

    resp = client.get("/api/tenant")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "tenant-a"


def test_org_claim_selects_tenant_not_request_params(client, login, two_tenants, member_a):
    # There is no request-side way to address tenant B: the tenant comes from
    # the token's org claim only. Query-string attempts change nothing.
    login(member_a, org_id="org_a")
    resp = client.get("/api/tenant/queries", params={"tenant": "tenant-b", "tenant_id": 2})
    assert [q["text"] for q in resp.json()] == ["query for A"]


def test_no_org_context_is_rejected(client, login, two_tenants, member_a):
    login(member_a, org_id=None)
    assert client.get("/api/tenant/queries").status_code == 403


def test_unknown_org_is_rejected(client, login, two_tenants, member_a):
    login(member_a, org_id="org_never_provisioned")
    assert client.get("/api/tenant/queries").status_code == 403


def test_anonymous_is_rejected(client, two_tenants):
    assert client.get("/api/tenant/queries").status_code == 401
    assert client.get("/api/admin/tenants").status_code == 401


def test_member_cannot_use_admin_routes(client, login, two_tenants, member_a):
    login(member_a, org_id="org_a")
    assert client.get("/api/admin/tenants").status_code == 403
    assert client.get("/api/admin/tenants/tenant-b").status_code == 403
    resp = client.post("/api/admin/tenants/tenant-b/import-yaml", content="brand: {name: X}")
    assert resp.status_code == 403


def test_membership_mirrored_from_org_claim(client, login, two_tenants, member_a, db_session):
    login(member_a, org_id="org_a", org_role="org:admin")
    assert client.get("/api/tenant").status_code == 200
    membership = db_session.exec(
        select(Membership).where(Membership.user_id == member_a.id)
    ).one()
    assert membership.role == MembershipRole.owner
    assert membership.tenant_id == two_tenants[0].id


def test_superadmin_sees_all_tenants_via_admin(client, login, two_tenants, db_session):
    superadmin = User(email="admin@example.com", clerk_user_id="user_sa", is_superadmin=True)
    db_session.add(superadmin)
    db_session.commit()
    db_session.refresh(superadmin)
    login(superadmin)
    resp = client.get("/api/admin/tenants")
    assert resp.status_code == 200
    assert {t["slug"] for t in resp.json()} == {"tenant-a", "tenant-b"}
