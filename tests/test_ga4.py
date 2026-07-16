"""GA4 AI-referral classifier + report parser. CI never calls GA4 — the parser
runs over a recorded-shape fixture; the authenticated fetch is not tested here."""

from engine.analytics.ga4 import build_report_request, classify_source, parse_report


def test_classify_source_maps_engines_and_ignores_the_rest():
    assert classify_source("chatgpt.com") == "ChatGPT"
    assert classify_source("openai.com") == "ChatGPT"
    assert classify_source("perplexity.ai") == "Perplexity"
    assert classify_source("perplexity") == "Perplexity"  # bare utm_source
    assert classify_source("claude.ai") == "Claude"
    assert classify_source("gemini.google.com") == "Gemini"
    assert classify_source("copilot.microsoft.com") == "Copilot"
    # Not AI traffic:
    assert classify_source("google") is None  # organic search, not Gemini
    assert classify_source("newsletter") is None
    assert classify_source("") is None


def test_build_report_request_shape():
    body = build_report_request("2026-06-01", "2026-06-28")
    assert body["dateRanges"][0] == {"startDate": "2026-06-01", "endDate": "2026-06-28"}
    assert {d["name"] for d in body["dimensions"]} == {"date", "sessionSource"}
    assert {m["name"] for m in body["metrics"]} == {"sessions", "keyEvents"}


FIXTURE = {
    "dimensionHeaders": [{"name": "date"}, {"name": "sessionSource"}],
    "metricHeaders": [{"name": "sessions"}, {"name": "keyEvents"}],
    "rows": [
        # Two ChatGPT sources on the same day (utm + referrer) must sum together.
        {"dimensionValues": [{"value": "20260601"}, {"value": "chatgpt.com"}],
         "metricValues": [{"value": "40"}, {"value": "3"}]},
        {"dimensionValues": [{"value": "20260601"}, {"value": "openai.com"}],
         "metricValues": [{"value": "10"}, {"value": "1"}]},
        {"dimensionValues": [{"value": "20260601"}, {"value": "perplexity.ai"}],
         "metricValues": [{"value": "12"}, {"value": "2"}]},
        # Non-AI traffic is dropped.
        {"dimensionValues": [{"value": "20260601"}, {"value": "google"}],
         "metricValues": [{"value": "500"}, {"value": "20"}]},
    ],
}


def test_parse_report_buckets_and_sums_by_engine():
    rows = parse_report(FIXTURE)
    assert rows == [
        {"date": "2026-06-01", "engine": "ChatGPT", "sessions": 50, "conversions": 4},
        {"date": "2026-06-01", "engine": "Perplexity", "sessions": 12, "conversions": 2},
    ]


def test_outcome_overlays_referrals_on_visibility(db_session):
    from api.dashboards_service import outcome
    from api.models import AiReferralDaily, SurfaceCode, Tenant, VisibilityDaily

    tenant = Tenant(name="Acme", slug="acme", ga4_property_id="123456789")
    db_session.add(tenant)
    db_session.commit()
    tid = tenant.id
    db_session.add(AiReferralDaily(tenant_id=tid, date="2026-06-01", engine="ChatGPT",
                                   sessions=50, conversions=4))
    db_session.add(AiReferralDaily(tenant_id=tid, date="2026-06-01", engine="Perplexity",
                                   sessions=12, conversions=2))
    db_session.add(VisibilityDaily(tenant_id=tid, date="2026-06-01",
                                   surface=SurfaceCode.openai_api, brand_score=80.0))
    db_session.commit()

    result = outcome(db_session, tid)
    assert result["connected"] is True and result["has_data"] is True
    assert result["totals"] == {"sessions": 62, "conversions": 6}
    assert result["series"][0] == {
        "date": "2026-06-01", "sessions": 62, "conversions": 6, "brand_score": 80.0,
    }
    assert result["engine_totals"][0]["engine"] == "ChatGPT"  # highest sessions first
