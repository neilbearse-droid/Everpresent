"""M5 reports (CSV/PDF) and run-completion email notifications."""

import csv
import io

from sqlmodel import select

from api.models import Tenant, User
from tests.test_dashboards import member, processed_run  # noqa: F401  (fixtures)
from tests.test_processing import configured_tenant  # noqa: F401
from tests.test_runs import (  # noqa: F401  (fixtures)
    _pending_run,
    fake_retrieve,
    job_env,
    make_tenant,
)


def test_results_csv(client, login, member, processed_run):  # noqa: F811
    login(member, org_id="org_smith")
    resp = client.get("/api/tenant/reports/results.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 4  # search-variant results only
    assert all(r["brand_mentioned"] == "True" for r in rows)
    assert all(r["citations"] == "2" for r in rows)


def test_visibility_csv(client, login, member, processed_run):  # noqa: F811
    login(member, org_id="org_smith")
    resp = client.get("/api/tenant/reports/visibility.csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 2  # two segments, one date
    assert rows[0]["brand_score"] == "83.33"
    assert "Rotman School of Management" in rows[0]


def test_summary_pdf(client, login, member, processed_run):  # noqa: F811
    login(member, org_id="org_smith")
    resp = client.get("/api/tenant/reports/summary.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 1000


def test_run_completion_email(db_session, job_env, fake_retrieve, configured_tenant, monkeypatch):  # noqa: F811
    from worker.jobs import run_mode_a

    sent: list[dict] = []
    monkeypatch.setattr("api.notifications.smtp_configured", lambda: True)
    monkeypatch.setattr(
        "api.notifications.send_email",
        lambda **kwargs: sent.append(kwargs) or True,
    )
    configured_tenant.notify_emails = ["neil@example.com", "client@smith.example"]
    db_session.add(configured_tenant)
    db_session.commit()

    run_id = _pending_run(db_session, configured_tenant)
    run_mode_a(run_id)

    assert len(sent) == 1
    email = sent[0]
    assert email["to"] == ["neil@example.com", "client@smith.example"]
    assert "run #" in email["subject"] and "complete" in email["subject"]
    names = [a.filename for a in email["attachments"]]
    assert any(n.endswith(".pdf") for n in names)
    assert any(n.endswith(".csv") for n in names)
    pdf = next(a for a in email["attachments"] if a.filename.endswith(".pdf"))
    assert pdf.content.startswith(b"%PDF")

    from api.models import Run

    run = db_session.get(Run, run_id)
    assert run is not None and run.counts.get("notified") == 2


def test_no_email_without_recipients_or_smtp(
    db_session, job_env, fake_retrieve, configured_tenant, monkeypatch  # noqa: F811
):
    from worker.jobs import run_mode_a

    sent: list[dict] = []
    monkeypatch.setattr("api.notifications.send_email", lambda **kw: sent.append(kw) or True)
    # SMTP unconfigured (default settings) — even with recipients, skip.
    configured_tenant.notify_emails = ["neil@example.com"]
    db_session.add(configured_tenant)
    db_session.commit()
    run_id = _pending_run(db_session, configured_tenant)
    run_mode_a(run_id)
    assert sent == []


def test_cap_alert_appears_at_80_percent(
    db_session, job_env, fake_retrieve, configured_tenant, monkeypatch  # noqa: F811
):
    from api.models import Run, RunStatus
    from worker.jobs import run_mode_a

    sent: list[dict] = []
    monkeypatch.setattr("api.notifications.smtp_configured", lambda: True)
    monkeypatch.setattr("api.notifications.send_email", lambda **kw: sent.append(kw) or True)
    configured_tenant.notify_emails = ["neil@example.com"]
    configured_tenant.monthly_spend_cap_usd = 1.00
    db_session.add(configured_tenant)
    # Cumulative month spend already at 85% of the cap (prior runs) — the
    # alert is about month-to-date spend crossing 80%, which is what the
    # reservation-based cap lets a run approach without overshooting.
    db_session.add(Run(tenant_id=configured_tenant.id, trigger="manual",
                       status=RunStatus.complete, cost_usd=0.85))
    db_session.commit()

    run_id = _pending_run(db_session, configured_tenant)
    run_mode_a(run_id)
    assert len(sent) == 1
    assert "SPEND ALERT" in sent[0]["body"]


def test_notify_emails_validated_in_admin(client, login, db_session):
    admin = User(email="neil@example.com", clerk_user_id="user_sa", is_superadmin=True)
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    login(admin)
    make_tenant(db_session)

    resp = client.patch("/api/admin/tenants/smith", json={"notify_emails": ["not-an-email"]})
    assert resp.status_code == 422
    resp = client.patch(
        "/api/admin/tenants/smith", json={"notify_emails": ["neil@example.com"]}
    )
    assert resp.status_code == 200
    tenant = db_session.exec(select(Tenant).where(Tenant.slug == "smith")).one()
    db_session.refresh(tenant)
    assert tenant.notify_emails == ["neil@example.com"]
