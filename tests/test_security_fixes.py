"""Fixes from the pre-demo security audit, each pinned by a test."""

import pytest

from tests.test_content import _seed_tenant


def _approved(db, monkeypatch, cap=100.0):
    from api.config import get_settings

    tenant, fact = _seed_tenant(
        db, ai_processing_approved=True, approved_utility_models=["claude-sonnet-4-6"],
        monthly_spend_cap_usd=cap,
    )
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    calls = []

    def _reply(*a, **k):
        calls.append(1)
        return '{"title": "t", "body": "b"}'

    monkeypatch.setattr("engine.llm.router.complete", _reply)
    return tenant, fact, calls


def test_drafts_count_toward_the_monthly_cap(db_session, monkeypatch):
    from api.config import get_settings
    from api.content_service import ContentGenUnavailable, generate_accuracy_draft
    from api.runs_service import month_spend_usd

    cost = get_settings().utility_draft_cost_usd
    tenant, fact, calls = _approved(db_session, monkeypatch, cap=cost * 3)
    for _ in range(3):
        generate_accuracy_draft(db_session, tenant, fact.id)
    assert month_spend_usd(db_session, tenant.id) == pytest.approx(cost * 3)
    with pytest.raises(ContentGenUnavailable, match="spend cap"):
        generate_accuracy_draft(db_session, tenant, fact.id)
    assert len(calls) == 3  # the 4th never reached the paid API


def test_drafts_are_rate_limited_per_hour(db_session, monkeypatch):
    from api.config import get_settings
    from api.content_service import ContentGenUnavailable, generate_accuracy_draft

    monkeypatch.setattr(get_settings(), "content_drafts_per_hour", 2)
    tenant, fact, calls = _approved(db_session, monkeypatch)
    generate_accuracy_draft(db_session, tenant, fact.id)
    generate_accuracy_draft(db_session, tenant, fact.id)
    with pytest.raises(ContentGenUnavailable, match="per hour"):
        generate_accuracy_draft(db_session, tenant, fact.id)
    assert len(calls) == 2


def test_archived_tenant_is_locked_out_and_not_run(client, login, db_session):
    from api.models import Tenant, TenantStatus, User

    t = Tenant(name="Old", slug="old", clerk_org_id="org_old", status=TenantStatus.archived)
    admin = User(email="a@x.test", clerk_user_id="u_a", is_superadmin=True)
    member = User(email="m@x.test", clerk_user_id="u_m")
    db_session.add_all([t, admin, member])
    db_session.commit()
    login(member, org_id="org_old", org_role="org:admin")
    assert client.get("/api/tenant").status_code == 403
    login(admin)
    assert client.post("/api/admin/tenants/old/runs").status_code == 409


def test_fix_urls_must_be_http(client, login, db_session):
    from api.models import Tenant, User

    db_session.add(Tenant(name="T", slug="t", clerk_org_id="org_t"))
    u = User(email="m@x.test", clerk_user_id="u_m")
    db_session.add(u)
    db_session.commit()
    login(u, org_id="org_t", org_role="org:admin")
    bad = client.post("/api/tenant/interventions",
                      json={"query_text": "q", "url": "javascript:alert(1)", "description": ""})
    assert bad.status_code == 422
    ok = client.post("/api/tenant/interventions",
                     json={"query_text": "q", "url": "https://godaddy.com/x", "description": ""})
    assert ok.status_code in (200, 201)


def test_csv_neutralizes_formulas_but_keeps_numbers():
    import csv
    import io

    from api.reports import _SafeCsvWriter

    out = io.StringIO()
    _SafeCsvWriter(out).writerow(
        ["=HYPERLINK(\"http://evil\")", "+1", "@SUM(A1)", "-cmd", -3.5, "ok"]
    )
    row = next(csv.reader(io.StringIO(out.getvalue())))
    assert row[:4] == ["'=HYPERLINK(\"http://evil\")", "'+1", "'@SUM(A1)", "'-cmd"]
    assert row[4:] == ["-3.5", "ok"]
