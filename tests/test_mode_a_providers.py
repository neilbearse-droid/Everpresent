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


def test_perplexity_agent_body_forces_search_and_maps_persona():
    body = pplx_body("You are a persona.", "best MBA?", model="sonar")
    # Agent API: legacy names map to the Perplexity-native slug, persona is
    # `instructions`, search is an explicit forced tool, and nothing else is
    # sent (unknown fields are rejected with a 400).
    assert body == {
        "model": "perplexity/sonar",
        "input": "best MBA?",
        "max_output_tokens": 1200,
        "instructions": "You are a persona.",
        "tools": [{"type": "web_search"}],
        "tool_choice": {"type": "web_search"},
    }
    assert pplx_body("p", "q", model="sonar-pro")["model"] == "perplexity/sonar"


def test_perplexity_agent_body_variants():
    assert "instructions" not in pplx_body("", "q", model="perplexity/sonar")
    nosearch = pplx_body("", "q", model="perplexity/sonar", web_search=False)
    assert "tools" not in nosearch and "tool_choice" not in nosearch
    natural = pplx_body("", "q", model="perplexity/sonar", force_search=False)
    assert natural["tools"] == [{"type": "web_search"}] and "tool_choice" not in natural


def test_perplexity_parses_agent_response():
    parsed = parse_perplexity_payload(json.loads((FIX / "perplexity_agent.json").read_text()))
    assert parsed.text.startswith("Wix and GoDaddy")
    assert [c.url for c in parsed.citations] == [
        "https://www.pcmag.com/picks/the-best-website-builders",
        "https://www.godaddy.com/websites/website-builder",
    ]
    assert parsed.fanout_queries == [
        "best website builder small business 2026", "GoDaddy vs Wix pricing",
    ]
    assert parsed.web_search_calls == 2
    assert parsed.input_tokens == 1040 and parsed.output_tokens == 220
    assert parsed.model == "perplexity/sonar"


def test_perplexity_cost_uses_sonar_prices():
    # Legacy sonar: $1/1M in, $1/1M out; + ONE request fee ($5/1k).
    cost = estimate_perplexity_cost_usd("sonar", 1_000_000, 1_000_000, 2)
    assert cost == round(1.0 + 1.0 + 5.0 / 1000, 6)
    assert estimate_perplexity_cost_usd("sonar", 0, 0, 0) == 0.0


def test_perplexity_agent_cost_bills_each_search():
    # Agent API: $0.25/1M in, $2.50/1M out, $2.50/1k per web_search call.
    cost = estimate_perplexity_cost_usd("perplexity/sonar", 1_000_000, 1_000_000, 2)
    assert cost == round(0.25 + 2.50 + 2 * 2.50 / 1000, 6)


# --- Anthropic Claude -------------------------------------------------------

def test_claude_parses_text_and_splits_cited_from_consulted():
    parsed = parse_claude_payload(
        json.loads((FIX / "claude_messages_web_search.json").read_text())
    )
    assert "Smith School of Business" in parsed.text
    # §AEO-plan M6: cited = what the answer text actually referenced; consulted
    # = search results the answer read but didn't cite.
    assert [c.url for c in parsed.citations] == [
        "https://smith.queensu.ca/programs/mba/full-time",
    ]
    assert [c.url for c in parsed.consulted_sources] == [
        "https://www.ft.com/mba-rankings/canada",
    ]
    assert parsed.web_search_calls == 1
    assert parsed.input_tokens == 320 and parsed.output_tokens == 96


def test_claude_captures_cited_text_snippet():
    payload = {
        "content": [
            {"type": "text", "text": "Smith is top-ranked.", "citations": [
                {"url": "https://ft.com/x", "title": "FT",
                 "cited_text": "Smith placed first in Canada for 2026." + "x" * 200},
            ]},
        ],
        "usage": {"input_tokens": 5, "output_tokens": 4,
                  "server_tool_use": {"web_search_requests": 1}},
        "model": "claude-x",
    }
    parsed = parse_claude_payload(payload)
    assert parsed.citations[0].cited_text.startswith("Smith placed first in Canada")
    assert len(parsed.citations[0].cited_text) == 150  # capped


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
    with_search = gemini_body("p", "q", model="gemini-2.5-flash", web_search=True)
    assert with_search["tools"] == [{"google_search": {}}]
    assert with_search["system_instruction"]["parts"][0]["text"] == "p"
    without = gemini_body("p", "q", model="gemini-2.5-flash", web_search=False)
    assert "tools" not in without


def test_gemini_body_caps_output_and_disables_flash_thinking():
    flash = gemini_body("p", "q", model="gemini-2.5-flash")
    assert flash["generationConfig"]["maxOutputTokens"] == 1200
    assert flash["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    # Pro can't disable thinking: minimum budget plus headroom so thinking
    # doesn't eat the answer.
    pro = gemini_body("p", "q", model="gemini-2.5-pro")
    assert pro["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 128}
    assert pro["generationConfig"]["maxOutputTokens"] > 1200
    # 2.0 models have no thinkingConfig and would reject one.
    old = gemini_body("p", "q", model="gemini-2.0-flash")
    assert "thinkingConfig" not in old["generationConfig"]


def test_empty_persona_prompt_is_omitted_everywhere():
    """The generic baseline persona has no prompt; no provider gets an empty
    system field (Gemini rejects an empty text part)."""
    from engine.retrievers.chatgpt_web import build_opening_message
    from engine.retrievers.claude_api import build_request_body as claude_body
    from engine.retrievers.openai_api import build_request_body as openai_body

    assert "system_instruction" not in gemini_body("", "q", model="gemini-2.5-flash")
    assert "system" not in claude_body("", "q", model="claude-sonnet-4-6")
    assert "instructions" not in pplx_body("  ", "q", model="sonar")
    assert "instructions" not in openai_body("", "q", model="gpt-5-mini")
    assert build_opening_message("", "best registrar?") == "best registrar?"
    # A real persona is still sent.
    assert gemini_body("You are X.", "q", model="gemini-2.5-flash")["system_instruction"]
    assert claude_body("You are X.", "q", model="claude-sonnet-4-6")["system"] == "You are X."


def test_gemini_citations_use_the_real_source_domain():
    from engine.retrievers.gemini_api import parse_gemini_payload

    parsed = parse_gemini_payload({"candidates": [{
        "content": {"parts": [{"text": "a"}]},
        "groundingMetadata": {"groundingChunks": [
            {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AbC",
                     "title": "godaddy.com"}},
            {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/XyZ",
                     "title": "Some Site Name"}},
        ], "webSearchQueries": ["q1", "q2", "q3"]},
    }]})
    assert parsed.citations[0].domain == "godaddy.com"
    # A title that isn't a domain falls back to the URL host.
    assert parsed.citations[1].domain == "vertexaisearch.cloud.google.com"


def test_citation_domain_is_the_normalized_host():
    from engine.retrievers.openai_api import ParsedCitation

    assert ParsedCitation(url="https://WWW.GoDaddy.com:443/x").domain == "godaddy.com"
    assert ParsedCitation(url="https://user:pw@wix.com/a").domain == "wix.com"


def test_gemini_grounding_billed_once_per_prompt():
    one = estimate_gemini_cost_usd("gemini-2.5-flash", 0, 0, 1)
    assert estimate_gemini_cost_usd("gemini-2.5-flash", 0, 0, 5) == one == 0.035
    assert estimate_gemini_cost_usd("gemini-2.5-flash", 0, 0, 0) == 0.0


def test_claude_web_search_capped_and_perplexity_output_capped():
    from engine.retrievers.claude_api import WEB_SEARCH_TOOL

    assert WEB_SEARCH_TOOL["max_uses"] == 3  # bounds the $10/1k fee tail
    assert pplx_body("p", "q", model="sonar")["max_output_tokens"] == 1200


def test_gemini_cost_uses_flash_prices():
    cost = estimate_gemini_cost_usd("gemini-2.5-flash", 1_000_000, 1_000_000, 1)
    assert cost == round(0.30 + 2.50 + 1 * 35.0 / 1000, 6)
