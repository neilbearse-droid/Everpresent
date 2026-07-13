"""chatgpt_web adapter: fixture-recorded parsing only — CI never scrapes
live (§11.5). The Playwright driver itself runs only in the scrape worker."""

from pathlib import Path

from engine.retrievers import chatgpt_web_selectors as sel
from engine.retrievers.chatgpt_web import build_opening_message, parse_assistant_html

FIXTURE_HTML = (
    Path(__file__).parent / "fixtures" / "chatgpt_web_message.html"
).read_text(encoding="utf-8")


def test_parses_text_from_rendered_message():
    text, _ = parse_assistant_html(FIXTURE_HTML)
    assert "Rotman School of Management" in text
    assert "Smith School of Business" in text
    assert "highly recommended for its 12-month program" in text
    # Block elements become line breaks, no HTML tags survive.
    assert "<" not in text
    assert text.count("\n") >= 4


def test_extracts_outbound_citations_only():
    _, citations = parse_assistant_html(FIXTURE_HTML)
    assert [c.url for c in citations] == [
        "https://www.ft.com/mba-rankings/canada",
        "https://smith.queensu.ca/programs/mba/employment-report",
    ]
    assert citations[0].domain == "ft.com"
    assert citations[1].domain == "smith.queensu.ca"
    assert citations[0].title == "FT Canadian MBA rankings"
    # chatgpt.com internal links are never sources.
    assert all("chatgpt.com" not in c.url for c in citations)


def test_deduplicates_repeated_links():
    html = FIXTURE_HTML + FIXTURE_HTML
    _, citations = parse_assistant_html(html)
    assert len(citations) == 2


def test_opening_message_is_persona_framing_plus_query():
    message = build_opening_message("You are an early retiree in Winnipeg.\n", "best insurance?")
    assert message == "You are an early retiree in Winnipeg.\n\nbest insurance?"


def test_selectors_live_in_the_selectors_file():
    # The five-minute-fix contract (§6.2): the adapter has no inline selectors.
    adapter_source = (
        Path(__file__).parent.parent / "engine" / "retrievers" / "chatgpt_web.py"
    ).read_text(encoding="utf-8")
    for name in ("PROMPT_INPUT", "SEND_BUTTON", "STOP_BUTTON", "ASSISTANT_MESSAGE"):
        assert getattr(sel, name)  # defined and non-empty
        assert getattr(sel, name) not in adapter_source  # not duplicated inline
