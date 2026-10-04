"""Ads layer: sponsored units cut from organic answers and reported apart."""

from sqlmodel import select

from api.models import (
    BrandProfile,
    Competitor,
    Mention,
    Result,
    ResultStatus,
    ResultVariant,
    Run,
    RunStatus,
    SponsoredUnit,
    SurfaceCode,
    Tenant,
)
from engine.processing.ads import split_sponsored_html, sponsored_from_serp
from engine.retrievers.html_extract import extract_text_and_links

ANSWER = """<div><p>For domains, Namecheap and Porkbun are popular picks.</p>
<div class="unit"><span>Sponsored</span><div>
  <a href="https://www.godaddy.com/offer">GoDaddy domains for $0.99</a><p>First-year deal</p>
</div></div>
<p>This guide is not sponsored by anyone.</p>
<div data-testid="ad-unit-1"><a href="https://www.wix.com/">Build a site</a></div>
<p>Ad hoc scripts also work. <a href="https://porkbun.com/">Porkbun</a></p></div>"""


def test_split_cuts_labelled_and_marked_units_only():
    organic, units = split_sponsored_html(ANSWER)
    assert "GoDaddy" not in organic and "wix.com" not in organic
    assert "not sponsored by anyone" in organic and "Ad hoc scripts" in organic
    assert [u.domain for u in units] == ["godaddy.com", "wix.com"]
    assert units[0].title == "GoDaddy domains for $0.99"
    text, links = extract_text_and_links(ANSWER, ())
    assert "GoDaddy" not in text and [c.domain for c in links] == ["porkbun.com"]


def test_no_ads_returns_input_untouched():
    html = "<p>Plain answer naming GoDaddy. <a href='https://x.com'>x</a></p>"
    assert split_sponsored_html(html) == (html, [])
    # A bare label with no link nearby is not an ad card.
    assert split_sponsored_html("<div><p>Sponsored</p><p>text</p></div>")[1] == []


def test_serp_ad_blocks():
    units = sponsored_from_serp({"ads": [{"title": "Hostinger", "link": "https://hostinger.com/x",
                                          "description": "Cheap hosting"}],
                                 "organic_results": [{"title": "not an ad"}]})
    assert [(u.title, u.domain, u.placement) for u in units] == [
        ("Hostinger", "hostinger.com", "serp")]


def test_processing_stores_units_and_keeps_mentions_organic(db_session, monkeypatch):
    from api.ads_service import ads_report
    from api.processing_service import process_run

    t = Tenant(name="GoDaddy", slug="gd")
    db_session.add(t)
    db_session.commit()
    db_session.add(BrandProfile(tenant_id=t.id, brand_name="GoDaddy", domains=["godaddy.com"]))
    db_session.add_all([Competitor(tenant_id=t.id, name="Namecheap", domains=["namecheap.com"]),
                        Competitor(tenant_id=t.id, name="Wix", domains=["wix.com"])])
    run = Run(tenant_id=t.id, trigger="manual", status=RunStatus.complete)
    db_session.add(run)
    db_session.commit()
    r = Result(run_id=run.id, tenant_id=t.id, query_text="q", persona_name="generic",
               surface=SurfaceCode.chatgpt_web, variant=ResultVariant.search,
               status=ResultStatus.ok, raw_uri="x")
    db_session.add(r)
    db_session.commit()
    organic_text, _ = extract_text_and_links(ANSWER, ())
    monkeypatch.setattr("api.processing_service._envelope", lambda result, session: {
        "parsed_text": organic_text, "response": {"html": ANSWER}})
    counts = process_run(db_session, run)
    assert counts["sponsored_units"] == 2
    units = {u.advertiser: u for u in db_session.exec(select(SponsoredUnit)).all()}
    assert units["GoDaddy"].advertiser_type == "brand"
    assert units["Wix"].advertiser_type == "competitor"
    names = {m.entity_name for m in db_session.exec(select(Mention)).all()}
    assert "GoDaddy" not in names and "Namecheap" in names  # paid ≠ organic
    rep = ads_report(db_session, t.id)
    assert rep["has_data"] and rep["units"] == 2 and rep["brand_share"] == 50.0
    assert rep["engines"][0]["ad_rate"] == 100.0
