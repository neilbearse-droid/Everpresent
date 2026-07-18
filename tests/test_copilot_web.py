"""copilot_web adapter: fixture-recorded parsing only — CI never scrapes live
(§11.5). The Playwright driver runs only in the scrape worker. Copilot is the
non-optional 5th platform for the GoDaddy demo (Bing-index-driven, browser
only)."""

from pathlib import Path

from engine.retrievers import copilot_web_selectors as sel
from engine.retrievers.copilot_web import parse_answer_html

FIXTURE_HTML = (
    Path(__file__).parent / "fixtures" / "copilot_web_message.html"
).read_text(encoding="utf-8")


def test_parses_text_from_rendered_answer():
    text, _ = parse_answer_html(FIXTURE_HTML)
    assert "Hostinger" in text and "Bluehost" in text
    assert "renewal pricing" in text
    assert "<" not in text  # block elements → line breaks, no tags survive


def test_extracts_external_citations_dropping_microsoft_chrome():
    _, citations = parse_answer_html(FIXTURE_HTML)
    urls = [c.url for c in citations]
    assert "https://www.reddit.com/r/webhosting/comments/xyz/best_host_2026/" in urls
    assert "https://www.hostinger.com/tutorials/best-hosting" in urls
    # Copilot/Bing internal links are chrome, never answer sources.
    assert all("copilot.microsoft.com" not in u for u in urls)
    assert all("bing.com" not in u for u in urls)
    domains = {c.domain for c in citations}
    assert {"reddit.com", "hostinger.com"} <= domains


def test_selectors_live_in_the_selectors_file():
    # The five-minute-fix contract (§6.2): the adapter carries no inline
    # selector strings — all live in copilot_web_selectors.py candidate lists.
    adapter_source = (
        Path(__file__).parent.parent / "engine" / "retrievers" / "copilot_web.py"
    ).read_text(encoding="utf-8")
    for name in (
        "PROMPT_INPUT_CANDIDATES",
        "SUBMIT_BUTTON_CANDIDATES",
        "ANSWER_CONTAINER_CANDIDATES",
        "STOP_BUTTON_CANDIDATES",
    ):
        candidates = getattr(sel, name)
        assert candidates  # defined and non-empty
        for selector in candidates:
            assert selector not in adapter_source  # not duplicated inline


def test_copilot_registered_as_mode_b_surface():
    from api.models import SurfaceCode
    from api.runs_service import MODE_B_SURFACES
    from worker.jobs import B_ADAPTERS

    assert SurfaceCode.copilot_web in MODE_B_SURFACES
    assert "copilot_web" in B_ADAPTERS
    module, label, rate_attr, timeout_attr = B_ADAPTERS["copilot_web"]
    assert label == "copilot-web"
    from api.config import get_settings

    settings = get_settings()
    assert hasattr(settings, rate_attr) and hasattr(settings, timeout_attr)
