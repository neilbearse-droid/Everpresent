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


_TIER1_HTML = """
<html><body>
<h2>What is the best MBA in Canada?</h2>
<p>Smith School of Business is the top-ranked MBA in Canada, with 92% of
graduates employed within three months and an average salary of $110,000,
according to the 2026 QS rankings and the Financial Times survey of alumni
outcomes across the country.</p>
<blockquote>"Smith produced our strongest hires," said a Fortune 500 recruiter.</blockquote>
<p>Tuition is $95,000. Class size is 80. See <a href="https://ft.com/x">FT</a>
and <a href="https://qs.com/y">QS</a> for the underlying data.</p>
</body></html>
"""

_PROMO_HTML = """
<html><body><h1>Our Platform</h1>
<p>Our world-class, best-in-class, industry-leading, cutting-edge platform is a
revolutionary game-changer. Unlock seamless, effortless value and supercharge
your team with our unparalleled state-of-the-art solution. Look no further.</p>
</body></html>
"""


def test_extract_features_tier1_signals():
    f = extract_features(_TIER1_HTML)
    assert f["has_answer_capsule"] is True          # 40-60 word answer under a "?" H2
    assert f["statistic_count"] >= 4                 # 92%, $110,000, 2026, $95,000, 80
    assert f["quotation_count"] >= 1                 # the recruiter blockquote/quote
    assert f["citation_count"] >= 2                  # ft.com + qs.com
    assert f["front_loaded"] is True                 # stats in the first third
    assert f["promotional_tone_score"] < 5.0


def test_extract_features_flags_promotional_tone():
    f = extract_features(_PROMO_HTML)
    # Marketing-voice lexicon is dense here → high penalty score, no capsule.
    assert f["promotional_tone_score"] >= 20.0
    assert f["has_answer_capsule"] is False


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
    assert pages["https://globex.com/why"]["on_page"] is None  # no presence row for a rival


def test_crawl_versions_pages_and_reads_changes_as_experiments(db_session, monkeypatch):
    from api.models import Intervention, PageChange, PageSnapshot
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
    db_session.add(Citation(result_id=r.id, tenant_id=tid, url="https://g2.com/best-crm",
                            domain="g2.com", source_category="other"))
    db_session.add(Citation(result_id=r.id, tenant_id=tid, url="https://globex.com/why",
                            domain="globex.com", source_category="competitor"))
    db_session.commit()
    html = {"value": PAGE_HTML}
    monkeypatch.setattr(page_crawl, "_engine", lambda: db_session.get_bind())
    monkeypatch.setattr(page_crawl, "crawl_page", lambda client, url: {
        "html": html["value"] if "g2.com" in url else PAGE_HTML, "http_status": 200})

    # First crawl: a baseline version of the third-party page and of the
    # rival's own page, which is fetched for this alone.
    page_crawl.crawl_power_pages(tid)
    versions = {v.url: v for v in db_session.exec(select(PageSnapshot)).all()}
    assert set(versions) == {"https://g2.com/best-crm", "https://globex.com/why"}
    assert versions["https://globex.com/why"].owner == "competitor"
    assert versions["https://globex.com/why"].owner_name == "Globex"
    assert versions["https://g2.com/best-crm"].features["headings"]
    assert [p.url for p in db_session.exec(select(PagePresence)).all()] == [
        "https://g2.com/best-crm"]

    # Same pages again: nothing new.
    page_crawl.crawl_power_pages(tid)
    assert len(db_session.exec(select(PageSnapshot)).all()) == 2
    assert db_session.exec(select(PageChange)).all() == []

    # The list now names the brand: a change, and an experiment on the
    # question that page is cited for, though nobody logged anything.
    html["value"] = PAGE_HTML.replace("</body>", "<p>Acme is a newer option.</p></body>")
    page_crawl.crawl_power_pages(tid)
    changes = db_session.exec(select(PageChange)).all()
    assert [(c.url, c.kind) for c in changes] == [("https://g2.com/best-crm", "brand_added")]
    [fix] = db_session.exec(select(Intervention)).all()
    assert (fix.source, fix.subject, fix.questions) == ("detected", "", ["best crm"])
    assert fix.description == "You now appear on this page" and changes[0].intervention_id == fix.id
