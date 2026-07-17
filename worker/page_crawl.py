"""Power Pages presence crawl (§focus-group #2).

For a tenant's top Power Pages (the URLs the engines cite), fetch each page
and record whether the brand/competitors are named on it plus the citability
fingerprint. Upserts page_presence keyed (tenant, url). Runs nightly for every
tenant with citations, and on demand from the admin panel. Competitor-owned
URLs are skipped; the brand's own cited pages ARE crawled — their fingerprint
is the "your page" side of the citability diff (§focus-group #3)."""

import httpx
import structlog
from sqlmodel import Session, select

from api.dashboards_service import citations_intel
from api.models import BrandProfile, Competitor, PagePresence, Tenant, utcnow
from engine.audit.presence import crawl_page, detect_presence, extract_features

log = structlog.get_logger()

MAX_PAGES = 20
TIMEOUT_S = 10.0


def crawl_power_pages(tenant_id: int) -> int:
    with Session(_engine()) as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            return 0
        brand = session.exec(
            select(BrandProfile).where(BrandProfile.tenant_id == tenant_id)
        ).first()
        brand_names = [brand.brand_name, *brand.aliases] if brand else [tenant.name]
        competitors = [
            (c.name, c.aliases)
            for c in session.exec(
                select(Competitor).where(Competitor.tenant_id == tenant_id)
            ).all()
        ]
        pages = [
            p for p in citations_intel(session, tenant_id)["power_pages"]
            if p["category"] != "competitor"
        ][:MAX_PAGES]

        crawled = 0
        with httpx.Client(timeout=TIMEOUT_S, follow_redirects=True) as client:
            for page in pages:
                fetched = crawl_page(client, page["url"])
                row = session.exec(
                    select(PagePresence).where(
                        PagePresence.tenant_id == tenant_id, PagePresence.url == page["url"]
                    )
                ).first()
                if row is None:
                    row = PagePresence(tenant_id=tenant_id, url=page["url"])
                row.domain = page["domain"]
                row.http_status = fetched.get("http_status")
                row.fetched_at = utcnow()
                if "error" in fetched or (fetched.get("http_status") or 600) >= 400:
                    row.status = "error"
                    row.error = fetched.get("error") or f"HTTP {fetched.get('http_status')}"
                else:
                    html = fetched["html"]
                    presence = detect_presence(html, brand_names, competitors)
                    row.status = "ok"
                    row.error = None
                    row.brand_found = presence["brand_found"]
                    row.competitors_found = presence["competitors_found"]
                    row.features = extract_features(html)
                session.add(row)
                session.commit()
                crawled += 1
        log.info("page_crawl.done", tenant=tenant.slug, pages=crawled)
        return crawled


def _engine():
    from api.db import get_engine

    return get_engine()
