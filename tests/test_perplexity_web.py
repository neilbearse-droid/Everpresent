"""perplexity_web adapter: fixture-recorded parsing only (§11.5)."""

from pathlib import Path

from engine.retrievers import perplexity_web_selectors as sel
from engine.retrievers.perplexity_web import parse_answer_html

FIXTURE_HTML = (
    Path(__file__).parent / "fixtures" / "perplexity_answer.html"
).read_text(encoding="utf-8")


def test_parses_answer_and_sources():
    text, citations = parse_answer_html(FIXTURE_HTML)
    assert "GreenShield's individual health plans" in text
    assert "<" not in text
    assert [c.url for c in citations] == [
        "https://www.greenshield.ca/en-ca/individuals",
        "https://www.sunlife.ca/en/health/personal-health-insurance/",
    ]
    assert citations[0].domain == "greenshield.ca"
    # perplexity.ai internal links are never sources.
    assert all("perplexity.ai" not in c.url for c in citations)


def test_selectors_live_in_the_selectors_file():
    adapter_source = (
        Path(__file__).parent.parent / "engine" / "retrievers" / "perplexity_web.py"
    ).read_text(encoding="utf-8")
    for name in ("PROMPT_INPUT", "SUBMIT_BUTTON", "STOP_BUTTON", "ANSWER_CONTAINER"):
        assert getattr(sel, name)
        assert getattr(sel, name) not in adapter_source
