"""Power Pages presence crawl (§focus-group #2): pure detection/fingerprint
logic plus the worker job end-to-end with a faked fetch — CI never crawls."""

from sqlmodel import select

from api.models import (
    BrandProfile,
    Citation,
    Competitor,
    PagePresence,
    Query,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SurfaceCode,
    Tenant,
)
from engine.audit.presence import detect_presence, extract_features

PAGE_HTML = """
<html><head><script type="application/ld+json">{"@type":"FAQPage"}</script></head>
<body>
<h1>Best CRMs of 2026</h1>
<p>Updated January 2026. Our top picks compared:</p>
<table><tr><td>Globex CRM</td><td>from $9</td></tr></table>
<p>Globex remains the leader, while Initech is a solid budget option.</p>
</body></html>
"""


def test_detect_presence_word_boundary_matching():
    presence = detect_presence(
        PAGE_HTML,
        brand_names=["Acme", "Acme CRM"],
        competitors=[("Globex", ["Globex CRM"]), ("Initech", []), ("Umbrella", [])],
    )
    assert presence["brand_found"] is False  # "Acme" nowhere on the page
    assert presence["competitors_found"] == ["Globex", "Initech"]

    named = detect_presence("<p>Acme is great</p>", ["Acme"], [])
    assert named["brand_found"] is True
    # Substring inside a longer word must NOT count.
    assert detect_presence("<p>Acmeology</p>", ["Acme"], [])["brand_found"] is False


def test_extract_features_fingerprint():
    features = extract_features(PAGE_HTML)
    assert features["json_ld"] is True
    assert features["faq_schema"] is True
    assert features["has_tables"] is True
    assert features["recent_year_mentions"] >= 2  # "2026" twice
    assert features["word_count"] > 10


def test_crawl_job_upserts_presence_and_feeds_power_pages(db_session, monkeypatch):
    from api.dashboards_service import citations_intel
    from worker import page_crawl

    tenant = Tenant(name="Acme", slug="acme")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(BrandProfile(tenant_id=tid, brand_name="Acme", domains=["acme.com"]))
    db_session.add(Competitor(tenant_id=tid, name="Globex", domains=["globex.com"]))
    db_session.add(Query(tenant_id=tid, text="best crm", corpus_tag="crm"))
    db_session.commit()
    run = Run(tenant_id=tid, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    r = Result(run_id=run.id, tenant_id=tid, query_text="best crm", persona_name="p",
               surface=SurfaceCode.openai_api, variant=ResultVariant.search,
               status=ResultStatus.ok)
    db_session.add(r)
    db_session.commit()
    # One third-party page (crawled) and one rival-owned page (skipped).
    db_session.add(Citation(result_id=r.id, tenant_id=tid, url="https://g2.com/best-crm",
                            domain="g2.com", source_category="other"))
    db_session.add(Citation(result_id=r.id, tenant_id=tid, url="https://globex.com/why",
                            domain="globex.com", source_category="competitor"))
    db_session.commit()

    monkeypatch.setattr(page_crawl, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(page_crawl, "crawl_page",
                        lambda client, url: {"html": PAGE_HTML, "http_status": 200})

    assert page_crawl.crawl_power_pages(tid) == 1  # only the third-party page

    rows = db_session.exec(select(PagePresence)).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.url == "https://g2.com/best-crm"
    assert row.status == "ok" and row.brand_found is False
    assert row.competitors_found == ["Globex"]
    assert row.features["faq_schema"] is True

    # Re-run upserts (no duplicate row), and citations_intel carries the join.
    assert page_crawl.crawl_power_pages(tid) == 1
    assert len(db_session.exec(select(PagePresence)).all()) == 1
    pages = {p["url"]: p for p in citations_intel(db_session, tid)["power_pages"]}
    g2 = pages["https://g2.com/best-crm"]
    assert g2["on_page"] is False and g2["competitors_on_page"] == ["Globex"]
    assert g2["page_features"]["has_tables"] is True
    assert pages["https://globex.com/why"]["on_page"] is None  # rival page not crawled
