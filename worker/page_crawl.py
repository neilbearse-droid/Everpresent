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

from api.config import get_settings
from api.dashboards_service import citations_intel
from api.models import BrandFact, BrandProfile, Competitor, PagePresence, Tenant, utcnow
from engine.audit.presence import crawl_page, detect_presence, extract_features, visible_html
from engine.netguard import guard_public_request
from engine.processing.accuracy import FactSpec, check_text
from engine.processing.citations import domain_is_owned
from engine.retrievers.html_extract import extract_text_and_links

log = structlog.get_logger()

MAX_PAGES = 20
MAX_OWN_PAGES = 15  # the brand's own cited pages, on top of MAX_PAGES
TIMEOUT_S = 10.0

# Power pages are the cited sources — Reddit threads, affiliate/review pages —
# and those routinely 403 a datacenter IP. Route the crawl through the same
# residential proxy the scrapers use (when set) and present a browser UA so the
# fetch looks like a real reader (§SCRAPING_V3). Empty proxy = direct, as before.
_CRAWL_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def crawl_power_pages(tenant_id: int) -> int:
    # Phase 1 — load config, then RELEASE the connection. A DB connection must
    # not be held across the ~20 sequential page fetches below (§connection-
    # lifetime): each fetch can take up to TIMEOUT_S, so holding one would pin a
    # pool slot for minutes of pure network wait.
    with Session(_engine()) as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            return 0
        tenant_slug = tenant.slug
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
        power = citations_intel(session, tenant_id)["power_pages"]
        # The brand's own cited pages first (ChatGPT now checks facts on
        # them, m33), then the third-party pages, up to the crawl budget.
        own = [p for p in power if p["category"] == "brand"][:MAX_OWN_PAGES]
        others = [p for p in power if p["category"] not in ("competitor", "brand")]
        pages = (own + others)[:MAX_PAGES + MAX_OWN_PAGES]
        owned_domains = [d.lower().removeprefix("www.") for d in (brand.domains if brand else [])]
        facts = [
            FactSpec(id=f.id, category=f.category, label=f.label, subject=f.subject,
                     aliases=list(f.aliases or []), kind=f.kind, expected=f.expected)
            for f in session.exec(
                select(BrandFact).where(
                    BrandFact.tenant_id == tenant_id, BrandFact.active == True  # noqa: E712
                )
            ).all()
            if f.id is not None
        ]

    if not pages:
        log.info("page_crawl.done", tenant=tenant_slug, pages=0)
        return 0

    # Phase 2 — fetch + parse each page. NO DB CONNECTION HELD.
    proxy = get_settings().scrape_proxy_url or None
    parsed: list[dict] = []
    # Cited URLs are outsider-controlled: public http(s) only, every hop.
    with httpx.Client(
        timeout=TIMEOUT_S, follow_redirects=True, proxy=proxy,
        headers={"User-Agent": _CRAWL_UA},
        event_hooks={"request": [guard_public_request]},
    ) as client:
        for page in pages:
            fetched = crawl_page(client, page["url"])
            row_data: dict = {
                "url": page["url"],
                "domain": page["domain"],
                "http_status": fetched.get("http_status"),
            }
            if "error" in fetched or (fetched.get("http_status") or 600) >= 400:
                row_data["status"] = "error"
                row_data["error"] = fetched.get("error") or f"HTTP {fetched.get('http_status')}"
            else:
                html = fetched["html"]
                presence = detect_presence(html, brand_names, competitors)
                row_data["status"] = "ok"
                row_data["error"] = None
                row_data["brand_found"] = presence["brand_found"]
                row_data["competitors_found"] = presence["competitors_found"]
                row_data["features"] = extract_features(html)
                if domain_is_owned(page["domain"], owned_domains):
                    # Own page: does it agree with the brand's fact sheet?
                    row_data["features"]["owned"] = True
                    row_data["features"]["fact_conflicts"] = _fact_conflicts(html, facts)
            parsed.append(row_data)

    # Phase 3 — persist with a fresh connection.
    with Session(_engine()) as session:
        crawled = 0
        for rd in parsed:
            row = session.exec(
                select(PagePresence).where(
                    PagePresence.tenant_id == tenant_id, PagePresence.url == rd["url"]
                )
            ).first()
            if row is None:
                row = PagePresence(tenant_id=tenant_id, url=rd["url"])
            row.domain = rd["domain"]
            row.http_status = rd["http_status"]
            row.fetched_at = utcnow()
            row.status = rd["status"]
            row.error = rd["error"]
            if rd["status"] == "ok":
                row.brand_found = rd["brand_found"]
                row.competitors_found = rd["competitors_found"]
                row.features = rd["features"]
            session.add(row)
            session.commit()
            crawled += 1
    log.info("page_crawl.done", tenant=tenant_slug, pages=crawled)
    return crawled


def _fact_conflicts(html: str, facts: list[FactSpec]) -> list[dict]:
    """Statements on the brand's own page that contradict its fact sheet
    (visible text only). Flagged as possible conflicts for a human to check:
    a pricing page lists several prices, and the detector reads sentences."""
    if not facts:
        return []
    text, _links = extract_text_and_links(visible_html(html), ())
    by_id = {f.id: f for f in facts}
    return [
        {"fact_id": h.fact_id, "subject": h.subject, "expected": h.expected,
         "stated": h.stated, "snippet": h.snippet[:240],
         "kind": by_id[h.fact_id].kind if h.fact_id in by_id else "",
         "label": by_id[h.fact_id].label if h.fact_id in by_id else ""}
        for h in check_text(text, facts)
    ][:10]


def _engine():
    from api.db import get_engine

    return get_engine()
