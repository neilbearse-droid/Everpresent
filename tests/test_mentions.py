"""Golden regression set for mention detection (DECISIONS.md M3.1 — this
pins v3-native behavior in lieu of the unavailable v1 regression set)."""

from engine.processing.mentions import detect_mentions

COMPETITORS: list[tuple[int | None, str, list[str]]] = [
    (11, "Rotman School of Management", ["Rotman", "UofT Rotman"]),
    (12, "Ivey Business School", ["Ivey"]),
    (13, "Schulich School of Business", ["Schulich"]),
]

TEXT = (
    "For a full-time MBA in Canada, Rotman is often the first name mentioned, "
    "but Smith School of Business at Queen's University is highly recommended "
    "for its one-year format. Ivey's case method is renowned, though it is "
    "expensive compared to Smith."
)


def test_detects_entities_with_rank_by_position():
    mentions = detect_mentions(TEXT, "Smith School of Business", ["Smith"], COMPETITORS)
    assert [(m.entity_name, m.rank) for m in mentions] == [
        ("Rotman School of Management", 1),
        ("Smith School of Business", 2),
        ("Ivey Business School", 3),
    ]
    brand = mentions[1]
    assert brand.entity_type == "brand"
    assert brand.matched_alias == "Smith School of Business"
    assert TEXT[brand.position : brand.position + 5] == "Smith"


def test_longest_alias_wins_and_shorter_alias_still_matches():
    # "Smith" alone appears later ("compared to Smith") — first occurrence is
    # via the full name, so position must be the full-name hit.
    mentions = detect_mentions(TEXT, "Smith School of Business", ["Smith"], [])
    assert len(mentions) == 1
    assert mentions[0].position == TEXT.index("Smith School of Business")


def test_word_boundaries_prevent_substring_hits():
    text = "GSCX Corp is unrelated; GSC itself is a benefits provider."
    mentions = detect_mentions(text, "GreenShield", ["GSC"], [])
    assert len(mentions) == 1
    assert mentions[0].position == text.index("GSC itself")


def test_case_insensitive():
    mentions = detect_mentions(
        "smith school of business ranks well.", "Smith School of Business", [], []
    )
    assert len(mentions) == 1 and mentions[0].position == 0


def test_sentiment_window():
    mentions = detect_mentions(TEXT, "Smith School of Business", ["Smith"], COMPETITORS)
    by_name = {m.entity_name: m for m in mentions}
    assert by_name["Smith School of Business"].sentiment == "positive"  # "highly recommended"
    assert by_name["Ivey Business School"].sentiment == "positive"  # "renowned" outweighs nothing
    ivey: list[tuple[int | None, str, list[str]]] = [(12, "Ivey Business School", ["Ivey"])]
    negative = detect_mentions(
        "Many reviewers say the program at Ivey is expensive and outdated.",
        "Smith",
        [],
        ivey,
    )
    assert negative[0].sentiment == "negative"


def test_snippet_is_bounded_and_contains_mention():
    mentions = detect_mentions(TEXT, "Smith School of Business", ["Smith"], [])
    snippet = mentions[0].context_snippet
    assert "Smith School of Business" in snippet
    assert len(snippet) <= 2 * 120 + len("Smith School of Business") + 2


def test_absent_entities_produce_no_mentions():
    assert detect_mentions("Nothing relevant here.", "Smith", ["SSB"], COMPETITORS) == []
