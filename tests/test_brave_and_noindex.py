"""Brave index check and noindex flag (M67). Claude's web search runs on
Brave and Brave's crawler follows Googlebot's rules, so an own page that is
noindexed or missing from Brave can't reach a Claude answer."""

import httpx

from api.models import BrandFact, Citation, PagePresence, utcnow
from engine.audit.brave import brave_indexed, normalize_url
from engine.audit.presence import extract_features
from tests.test_future_proof import _result, _tenant


def test_normalize_url_ignores_scheme_www_and_trailing_slash():
    assert normalize_url("https://www.Acme.com/Pricing/") == "acme.com/pricing"
    assert normalize_url("http://acme.com") == "acme.com/"
    assert normalize_url("https://acme.com/pricing?utm=x") == "acme.com/pricing"


def _client(status: int, urls: list[str]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "brave-key"
        assert request.url.params["q"] == "https://acme.com/pricing"
        return httpx.Response(status, json={"web": {"results": [{"url": u} for u in urls]}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_brave_indexed_matches_normalised_result_urls():
    with _client(200, ["https://www.acme.com/pricing/", "https://rival.com/"]) as c:
        assert brave_indexed("brave-key", "https://acme.com/pricing", c) is True
    with _client(200, ["https://acme.com/", "https://rival.com/pricing"]) as c:
        assert brave_indexed("brave-key", "https://acme.com/pricing", c) is False
    # No key, or the API refusing: unknown, never a flag.
    assert brave_indexed("", "https://acme.com/pricing") is None
    with _client(429, []) as c:
        assert brave_indexed("brave-key", "https://acme.com/pricing", c) is None


def test_extract_features_reads_noindex_meta():
    assert extract_features("<html><head><meta name=\"robots\" content=\"noindex, follow\">"
                            "</head><body>Hi</body></html>")["noindex"] is True
    assert extract_features("<html><head><meta name=\"googlebot\" content=\"NOINDEX\">"
                            "</head><body>Hi</body></html>")["noindex"] is True
    assert extract_features("<html><head><meta name=\"robots\" content=\"index, follow\">"
                            "</head><body>Hi</body></html>")["noindex"] is False


def test_own_pages_flags_noindex_and_brave_and_plays(db_session):
    from api.own_pages_service import own_pages
    from api.recommendations_service import _own_page_plays

    t = _tenant(db_session)
    r = _result(db_session, t.id)
    for url in ("https://acme.com/hidden", "https://acme.com/unseen", "https://acme.com/fine"):
        db_session.add(Citation(result_id=r.id, tenant_id=t.id, url=url, domain="acme.com",
                                link_kind="inline"))
    db_session.add(BrandFact(tenant_id=t.id, label="x", subject="x", expected="1", kind="numeric"))
    year = utcnow().year
    db_session.add(PagePresence(tenant_id=t.id, url="https://acme.com/hidden", domain="acme.com",
                                status="ok", features={"has_updated_date": True,
                                                       "latest_year": year, "noindex": True,
                                                       "brave_indexed": False}))
    db_session.add(PagePresence(tenant_id=t.id, url="https://acme.com/unseen", domain="acme.com",
                                status="ok", features={"has_updated_date": True,
                                                       "latest_year": year,
                                                       "brave_indexed": False}))
    db_session.add(PagePresence(tenant_id=t.id, url="https://acme.com/fine", domain="acme.com",
                                status="ok", features={"has_updated_date": True,
                                                       "latest_year": year,
                                                       "brave_indexed": True}))
    db_session.commit()

    rep = own_pages(db_session, t.id)
    assert rep["has_brave"] is True
    pages = {p["path"]: p for p in rep["pages"]}
    assert pages["/hidden"]["flags"] == ["noindex", "not in Brave"]
    assert pages["/unseen"]["flags"] == ["not in Brave"]
    assert pages["/fine"]["flags"] == []
    assert [p["path"] for p in rep["pages"]] == ["/hidden", "/unseen", "/fine"]  # worst first
    assert pages["/hidden"]["crawl"]["brave_indexed"] is False
    assert pages["/fine"]["crawl"]["noindex"] is False

    plays = {p.gap_ref: p for p in _own_page_plays(db_session, t.id)}
    assert "own_page:noindex:/hidden" in plays            # noindex wins over the Brave play
    assert "own_page:brave:/hidden" not in plays
    assert plays["own_page:brave:/unseen"].title == "Submit /unseen to Brave"
    assert "own_page:brave:/fine" not in plays


def test_pages_without_a_brave_check_are_not_flagged(db_session):
    from api.own_pages_service import own_pages

    t = _tenant(db_session)
    r = _result(db_session, t.id)
    db_session.add(Citation(result_id=r.id, tenant_id=t.id, url="https://acme.com/p",
                            domain="acme.com", link_kind="inline"))
    db_session.add(PagePresence(tenant_id=t.id, url="https://acme.com/p", domain="acme.com",
                                status="ok", features={"has_updated_date": True,
                                                       "latest_year": utcnow().year}))
    db_session.commit()
    rep = own_pages(db_session, t.id)
    assert rep["has_brave"] is False
    assert rep["pages"][0]["flags"] == []
    assert rep["pages"][0]["crawl"]["brave_indexed"] is None
