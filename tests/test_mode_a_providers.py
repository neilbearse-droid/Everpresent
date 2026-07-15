"""Parser and cost tests for the Mode A (API) providers beyond OpenAI. CI never
calls a provider or spends (§11.5) — every assertion runs over a recorded
fixture."""

import json
from pathlib import Path

from engine.costs import (
    estimate_anthropic_cost_usd,
    estimate_gemini_cost_usd,
    estimate_perplexity_cost_usd,
)
from engine.retrievers.claude_api import build_request_body as claude_body
from engine.retrievers.claude_api import parse_claude_payload
from engine.retrievers.gemini_api import build_request_body as gemini_body
from engine.retrievers.gemini_api import parse_gemini_payload
from engine.retrievers.perplexity_api import build_request_body as pplx_body
from engine.retrievers.perplexity_api import parse_perplexity_payload

FIX = Path(__file__).parent / "fixtures"


# --- Perplexity Sonar -------------------------------------------------------

def test_perplexity_parses_answer_and_citations():
    parsed = parse_perplexity_payload(json.loads((FIX / "perplexity_sonar.json").read_text()))
    assert "Smith School of Business" in parsed.text
    assert [c.url for c in parsed.citations] == [
        "https://www.ft.com/mba-rankings/canada",
        "https://smith.queensu.ca/programs/mba/full-time",
    ]
    assert parsed.citations[0].domain == "ft.com"
    assert parsed.web_search_calls == 2
    assert parsed.input_tokens == 210 and parsed.output_tokens == 88
    assert parsed.model == "sonar"


def test_perplexity_dedupes_search_results_and_citations():
    # search_results and the bare citations list overlap; each url appears once.
    parsed = parse_perplexity_payload(json.loads((FIX / "perplexity_sonar.json").read_text()))
    assert len(parsed.citations) == 2


def test_perplexity_body_maps_persona_to_system():
    body = pplx_body("You are a persona.", "best MBA?", model="sonar")
    assert body["messages"][0] == {"role": "system", "content": "You are a persona."}
    assert body["messages"][1] == {"role": "user", "content": "best MBA?"}


def test_perplexity_cost_uses_sonar_prices():
    # sonar: $1/1M in, $1/1M out; + 2 searches * $5/1k.
    cost = estimate_perplexity_cost_usd("sonar", 1_000_000, 1_000_000, 2)
    assert cost == round(1.0 + 1.0 + 2 * 5.0 / 1000, 6)


# --- Anthropic Claude -------------------------------------------------------

def test_claude_parses_text_and_deduped_citations():
    parsed = parse_claude_payload(
        json.loads((FIX / "claude_messages_web_search.json").read_text())
    )
    assert "Smith School of Business" in parsed.text
    # citations come from both the tool-result block and the text block, deduped
    assert [c.url for c in parsed.citations] == [
        "https://www.ft.com/mba-rankings/canada",
        "https://smith.queensu.ca/programs/mba/full-time",
    ]
    assert parsed.web_search_calls == 1
    assert parsed.input_tokens == 320 and parsed.output_tokens == 96


def test_claude_body_includes_web_search_tool_only_when_enabled():
    with_search = claude_body("p", "q", model="claude-sonnet-4-6", web_search=True)
    assert with_search["tools"][0]["name"] == "web_search"
    assert with_search["system"] == "p"
    without = claude_body("p", "q", model="claude-sonnet-4-6", web_search=False)
    assert "tools" not in without


def test_claude_cost_uses_sonnet_prices():
    cost = estimate_anthropic_cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000, 1)
    assert cost == round(3.0 + 15.0 + 1 * 10.0 / 1000, 6)


# --- Google Gemini ----------------------------------------------------------

def test_gemini_parses_text_and_grounding_citations():
    parsed = parse_gemini_payload(json.loads((FIX / "gemini_grounding.json").read_text()))
    assert "Smith School of Business" in parsed.text
    assert [c.url for c in parsed.citations] == [
        "https://www.ft.com/mba-rankings/canada",
        "https://smith.queensu.ca/programs/mba/full-time",
    ]
    assert parsed.web_search_calls == 2  # two webSearchQueries
    assert parsed.input_tokens == 180 and parsed.output_tokens == 74


def test_gemini_body_includes_google_search_only_when_enabled():
    with_search = gemini_body("p", "q", web_search=True)
    assert with_search["tools"] == [{"google_search": {}}]
    assert with_search["system_instruction"]["parts"][0]["text"] == "p"
    without = gemini_body("p", "q", web_search=False)
    assert "tools" not in without


def test_gemini_cost_uses_flash_prices():
    cost = estimate_gemini_cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000, 1)
    assert cost == round(0.30 + 2.50 + 1 * 35.0 / 1000, 6)
