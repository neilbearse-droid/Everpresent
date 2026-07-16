"""GA4 AI-referral pull (panel #6 / Outcome).

For each tenant with a GA4 property configured, run a GA4 Data API report of
daily sessions + key events by source, classify AI-referral traffic, and upsert
ai_referral_daily. Reuses the BigQuery mirror's service-account JWT grant (no
Google SDK); the shared SA must be granted Viewer on the tenant's property.
Never raises into the scheduler — a tenant's failure is logged and skipped.
"""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import structlog
from sqlmodel import Session, select

from api.config import get_settings
from api.db import get_engine
from api.models import AiReferralDaily, Tenant, utcnow
from engine.analytics.ga4 import build_report_request, parse_report

log = structlog.get_logger()

TOKEN_URL = "https://oauth2.googleapis.com/token"
GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GA4_BASE = "https://analyticsdata.googleapis.com/v1beta"


def _access_token(client: httpx.Client) -> str:
    settings = get_settings()
    key = json.loads(Path(settings.google_service_account_json).read_text(encoding="utf-8"))
    now = int(time.time())
    assertion = jwt.encode(
        {"iss": key["client_email"], "scope": GA4_SCOPE, "aud": TOKEN_URL,
         "iat": now, "exp": now + 3600},
        key["private_key"],
        algorithm="RS256",
    )
    resp = client.post(
        TOKEN_URL,
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _upsert(session: Session, tenant_id: int, rows: list[dict]) -> int:
    n = 0
    for row in rows:
        existing = session.exec(
            select(AiReferralDaily).where(
                AiReferralDaily.tenant_id == tenant_id,
                AiReferralDaily.date == row["date"],
                AiReferralDaily.engine == row["engine"],
            )
        ).first()
        if existing is None:
            existing = AiReferralDaily(tenant_id=tenant_id, date=row["date"], engine=row["engine"])
        existing.sessions = row["sessions"]
        existing.conversions = row["conversions"]
        existing.fetched_at = utcnow()
        session.add(existing)
        n += 1
    session.commit()
    return n


def pull_tenant(client: httpx.Client, token: str, session: Session, tenant: Tenant) -> int:
    settings = get_settings()
    start = (datetime.now(UTC) - timedelta(days=settings.ga4_lookback_days)).date().isoformat()
    end = datetime.now(UTC).date().isoformat()
    resp = client.post(
        f"{GA4_BASE}/properties/{tenant.ga4_property_id}:runReport",
        headers={"Authorization": f"Bearer {token}"},
        json=build_report_request(start, end),
    )
    resp.raise_for_status()
    rows = parse_report(resp.json())
    assert tenant.id is not None
    return _upsert(session, tenant.id, rows)


def pull_ga4_referrals() -> dict[str, int]:
    settings = get_settings()
    if not settings.google_service_account_json:
        log.info("ga4.skipped", reason="no service account configured")
        return {}
    out: dict[str, int] = {}
    with httpx.Client(timeout=60) as client, Session(get_engine()) as session:
        tenants = [
            t for t in session.exec(select(Tenant)).all()
            if t.ga4_property_id
        ]
        if not tenants:
            return {}
        token = _access_token(client)
        for tenant in tenants:
            try:
                out[tenant.slug] = pull_tenant(client, token, session, tenant)
                log.info("ga4.pulled", tenant=tenant.slug, rows=out[tenant.slug])
            except Exception:  # noqa: BLE001 — one tenant's failure never blocks the rest
                log.exception("ga4.pull_failed", tenant=tenant.slug)
    return out
