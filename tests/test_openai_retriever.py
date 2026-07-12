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
    # Search-disabled variant (dual-query diff, classifier lands M3).
    assert "tools" not in build_request_body("p", "q", model="gpt-4o", web_search=False)


def test_cost_estimate_matches_price_table():
    # gpt-4o: $2.50/M in, $10/M out; web search $10/1k calls.
    cost = estimate_openai_cost_usd("gpt-4o-2024-08-06", 1_000_000, 100_000, 10)
    assert cost == round(2.50 + 1.00 + 0.10, 6)
    # Longest-prefix match: -mini must not price as gpt-4o.
    assert estimate_openai_cost_usd("gpt-4o-mini", 1_000_000, 0, 0) == 0.15
