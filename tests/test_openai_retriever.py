"""Parser and cost tests over the recorded fixture — CI never scrapes or
spends (§11.5)."""

import json
from pathlib import Path

from engine.costs import estimate_openai_cost_usd
from engine.retrievers.openai_api import build_request_body, parse_responses_payload

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "openai_responses_web_search.json").read_text()
)


def test_parses_text_and_annotation_citations():
    parsed = parse_responses_payload(FIXTURE)
    assert "Smith School of Business" in parsed.text
    # Citations come from output[i].content[j].annotations — the fixture has
    # no top-level `sources` attribute, matching the real API (§4).
    assert "sources" not in FIXTURE
    assert [c.url for c in parsed.citations] == [
        "https://www.ft.com/mba-rankings/canada",
        "https://www.smith.queensu.ca/programs/mba/full-time",
    ]
    assert parsed.citations[0].domain == "ft.com"
    assert parsed.citations[1].domain == "smith.queensu.ca"
    assert parsed.web_search_calls == 1
    assert parsed.input_tokens == 1180
    assert parsed.output_tokens == 342
    assert parsed.model == "gpt-4o-2024-08-06"


def test_parser_tolerates_minimal_payload():
    parsed = parse_responses_payload({"output": [], "usage": {}})
    assert parsed.text == ""
    assert parsed.citations == []


def test_request_body_uses_persona_as_instructions():
    body = build_request_body("You are a persona.", "best MBA?", model="gpt-4o")
    assert body["instructions"] == "You are a persona."
    assert body["input"] == "best MBA?"
    assert body["tools"] == [{"type": "web_search"}]
    # Search is forced so gpt-4o reliably retrieves (and returns citations),
    # instead of often answering from training with no sources.
    assert body["tool_choice"] == {"type": "web_search"}
    # Cost cap: consumer-length answers, no runaway output billing.
    assert body["max_output_tokens"] == 1200
    assert "reasoning" not in body  # gpt-4o is not a reasoning model
    # Search-disabled variant (dual-query diff): no tool, no forcing.
    nosearch = build_request_body("p", "q", model="gpt-4o", web_search=False)
    assert "tools" not in nosearch and "tool_choice" not in nosearch


def test_gpt5_models_pin_low_reasoning_effort():
    # Reasoning tokens bill as output; low effort matches the consumer app's
    # fast default and bounds cost.
    body = build_request_body("p", "q", model="gpt-5.6-terra")
    assert body["reasoning"] == {"effort": "low"}
    assert body["max_output_tokens"] == 1200


def test_cost_estimate_matches_price_table():
    # gpt-4o: $2.50/M in, $10/M out; web search $10/1k calls.
    cost = estimate_openai_cost_usd("gpt-4o-2024-08-06", 1_000_000, 100_000, 10)
    assert cost == round(2.50 + 1.00 + 0.10, 6)
    # Longest-prefix match: -mini must not price as gpt-4o.
    assert estimate_openai_cost_usd("gpt-4o-mini", 1_000_000, 0, 0) == 0.15


def test_gpt5_family_pricing_resolves_by_tier():
    # The default model (Terra tier): $2.50/M in, $15/M out.
    assert estimate_openai_cost_usd("gpt-5.6-terra", 1_000_000, 1_000_000, 0) == 17.50
    # Longest-prefix keeps the tiers distinct and off the bare aliases.
    assert estimate_openai_cost_usd("gpt-5.6-luna", 1_000_000, 0, 0) == 1.00
    assert estimate_openai_cost_usd("gpt-5.6-sol", 0, 1_000_000, 0) == 30.00
    assert estimate_openai_cost_usd("gpt-5.6", 1_000_000, 0, 0) == 5.00  # bare alias = Sol
    assert estimate_openai_cost_usd("gpt-5", 1_000_000, 0, 0) == 1.25
    assert estimate_openai_cost_usd("gpt-5-mini", 1_000_000, 0, 0) == 0.25
