"""GoogleAIOSignal classifier (provisional rules — see DECISIONS.md M6) and
the AIO capture parsers. Fixture-only; CI never touches Google."""

import json
from pathlib import Path

from engine.processing.aio import (
    AIO_CLASSIFIER_VERSION,
    AIOSourceType,
    GoogleAIOSignal,
    classify_aio_capture,
)
from engine.retrievers.google_aio import (
    AIOCaptureSummary,
    parse_aio_fragment,
    parse_serpapi_payload,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_signal_defaults_match_spec():
    # §5.2: defaults describe "AIO retrieval did not run".
    signal = GoogleAIOSignal()
    assert signal.triggered is False
    assert signal.confidence == 0.0
    assert signal.source_type == AIOSourceType.no_aio
    assert signal.cited_urls == [] and signal.cited_domains == []


def test_classifier_buckets():
    def summary(**kw) -> AIOCaptureSummary:
        base: dict = dict(ran=True, aio_present=True, aio_position_index=0,
                          aio_text_len=500, expanded=False, organic_count=10)
        base.update(kw)
        return AIOCaptureSummary(**base)  # pyright: ignore[reportArgumentType]

    assert classify_aio_capture(AIOCaptureSummary(ran=False), []).source_type == "no_aio"
    assert classify_aio_capture(AIOCaptureSummary(ran=False), []).confidence == 0.0

    absent = classify_aio_capture(summary(aio_present=False, aio_position_index=-1), [])
    assert absent.source_type == "no_aio" and absent.confidence == 0.9

    dominant = classify_aio_capture(summary(expanded=True), ["https://a.com/x"])
    assert dominant.source_type == "aio_dominant" and dominant.triggered

    long_text = classify_aio_capture(summary(aio_text_len=1300), [])
    assert long_text.source_type == "aio_dominant"

    modest = classify_aio_capture(summary(), [])
    assert modest.source_type == "aio_plus_organic"

    below = classify_aio_capture(summary(aio_position_index=1), [])
    assert below.source_type == "organic_dominant"

    assert dominant.classifier_version == AIO_CLASSIFIER_VERSION


def test_cited_domains_deduped():
    signal = classify_aio_capture(
        AIOCaptureSummary(aio_present=True, aio_position_index=0, aio_text_len=100),
        [
            "https://www.smith.queensu.ca/a",
            "https://smith.queensu.ca/b",
            "https://ft.com/c",
        ],
    )
    assert signal.cited_domains == ["smith.queensu.ca", "ft.com"]


def test_parse_aio_fragment():
    html = (FIXTURES / "google_aio_block.html").read_text(encoding="utf-8")
    text, citations = parse_aio_fragment(html)
    assert "one-year MBA" in text
    assert [c.domain for c in citations] == ["smith.queensu.ca", "ft.com"]
    # google-internal links excluded
    assert all("google.com" not in c.url for c in citations)


def test_parse_serpapi_payload():
    payload = json.loads((FIXTURES / "serpapi_aio.json").read_text(encoding="utf-8"))
    outcome = parse_serpapi_payload(payload)
    assert outcome.summary.aio_present is True
    assert outcome.summary.aio_position_index == 0
    assert outcome.summary.organic_count == 2
    assert "strong one-year option" in outcome.aio_text
    assert [c.domain for c in outcome.citations] == ["smith.queensu.ca", "ft.com"]


def test_serpapi_without_aio():
    outcome = parse_serpapi_payload({"organic_results": [{}, {}, {}]})
    assert outcome.summary.aio_present is False
    assert outcome.summary.aio_position_index == -1
    assert outcome.summary.organic_count == 3


def test_serpapi_expands_a_lazy_ai_overview(monkeypatch):
    """When SerpApi returns only a page_token, the adapter fetches the full
    Overview (second, billed search) instead of recording it as empty."""
    import asyncio

    from engine.retrievers import google_aio

    calls: list[dict] = []

    class _Resp:
        def __init__(self, body):
            self._body, self.status_code = body, 200

        def json(self):
            return self._body

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params):
            calls.append(params)
            if params["engine"] == "google":
                return _Resp({"ai_overview": {"page_token": "tok"}, "organic_results": [{}, {}]})
            return _Resp({"ai_overview": {
                "text_blocks": [{"snippet": "GoDaddy and Namecheap are popular registrars."}],
                "references": [{"link": "https://www.godaddy.com/domains", "title": "GoDaddy"}],
            }})

    monkeypatch.setattr(google_aio.httpx, "AsyncClient", _Client)
    out = asyncio.run(google_aio._capture_serpapi(
        "best domain registrar", gl="us", hl="en", api_key="k", timeout_s=5,
    ))
    assert [c["engine"] for c in calls] == ["google", "google_ai_overview"]
    assert calls[1]["page_token"] == "tok"
    assert "GoDaddy" in out.aio_text
    assert out.citations[0].domain == "godaddy.com"
    assert out.summary.aio_present and out.summary.organic_count == 2
    assert out.extra_searches == 1
