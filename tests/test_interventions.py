"""Intervention ledger (§CMO #1): before/after measurement with control group,
plus the tenant-scoped CRUD routes."""

from datetime import UTC, datetime

from sqlmodel import select

from api.dashboards_service import interventions_report
from api.models import (
    Intervention,
    Mention,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
    User,
)

BEFORE = datetime(2026, 6, 1, tzinfo=UTC)
SHIP = datetime(2026, 6, 10, tzinfo=UTC)
AFTER = datetime(2026, 6, 20, tzinfo=UTC)


def _result(db, run_id, tid, qtext, created, *, brand=False, surface="openai_api"):
    r = Result(run_id=run_id, tenant_id=tid, query_text=qtext, persona_name="p",
               surface=SurfaceCode(surface), variant=ResultVariant.search,
               status=ResultStatus.ok, created_at=created)
    db.add(r)
    db.commit()
    db.refresh(r)
    if brand:
        db.add(Mention(result_id=r.id, tenant_id=tid, entity_type="brand",
                       entity_name="Acme", position=0, rank=1))
        db.commit()
    return r


def _setup(db):
    tenant = Tenant(name="Acme", slug="acme", clerk_org_id="org_acme")
    db.add(tenant)
    db.commit()
    run = Run(tenant_id=tenant.id, trigger="manual", status=RunStatus.complete)
    db.add(run)
    db.commit()
    return tenant, run


def test_report_measures_lift_vs_control_and_engine_flips(db_session):
    tenant, run = _setup(db_session)
    tid = tenant.id
    # Treated query: absent before ship (2 engines), present after on openai.
    _result(db_session, run.id, tid, "q fix", BEFORE, brand=False, surface="openai_api")
    _result(db_session, run.id, tid, "q fix", BEFORE, brand=False, surface="claude_api")
    _result(db_session, run.id, tid, "q fix", AFTER, brand=True, surface="openai_api")
    _result(db_session, run.id, tid, "q fix", AFTER, brand=False, surface="claude_api")
    # Control query: absent throughout.
    _result(db_session, run.id, tid, "q ctrl", BEFORE, brand=False)
    _result(db_session, run.id, tid, "q ctrl", AFTER, brand=False)
    db_session.add(Intervention(tenant_id=tid, query_text="q fix", url="https://acme.com/new",
                                shipped_at=SHIP, created_by="neil@x"))
    db_session.commit()

    report = interventions_report(db_session, tid)
    item = report["interventions"][0]
    assert item["before_rate"] == 0.0 and item["after_rate"] == 50.0
    assert item["delta"] == 50.0
    assert item["control_delta"] == 0.0
    assert item["newly_visible"] == ["openai_api"]
    assert item["awaiting"] is False
    assert report["aggregate"] == {"measured": 1, "avg_delta": 50.0,
                                   "avg_control_delta": 0.0}


def test_report_awaits_post_ship_runs(db_session):
    tenant, run = _setup(db_session)
    tid = tenant.id
    _result(db_session, run.id, tid, "q fix", BEFORE, brand=False)
    db_session.add(Intervention(tenant_id=tid, query_text="q fix", shipped_at=SHIP))
    db_session.commit()

    report = interventions_report(db_session, tid)
    item = report["interventions"][0]
    assert item["awaiting"] is True and item["after_rate"] is None and item["delta"] is None
    assert report["aggregate"] is None


def test_intervention_routes_scoped_to_org(client, login, db_session):
    tenant, _run = _setup(db_session)
    user = User(email="member@acme.example", clerk_user_id="user_acme")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    login(user, org_id="org_acme")

    created = client.post("/api/tenant/interventions", json={
        "query_text": "q fix", "url": "https://acme.com/new", "shipped_at": "2026-06-10",
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_by"] == "member@acme.example"

    listed = client.get("/api/tenant/interventions").json()
    assert len(listed["interventions"]) == 1
    assert listed["interventions"][0]["shipped_at"] == "2026-06-10"

    bad = client.post("/api/tenant/interventions", json={"query_text": "  "})
    assert bad.status_code == 422

    gone = client.delete(f"/api/tenant/interventions/{body['id']}")
    assert gone.status_code == 204
    assert db_session.exec(select(Intervention)).all() == []
