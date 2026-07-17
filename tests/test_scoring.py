"""Golden regression set for visibility scoring (DECISIONS.md M3.1)."""

from engine.processing.citations import categorize_domain, classify_source_type
from engine.processing.scoring import ResultSignals, score_entity, share_of_voice


def test_score_formula_exact():
    # 4 results: mentioned first w/ brand citation; mentioned third; absent; absent
    signals = [
        ResultSignals(mention_rank=1, cited=True),
        ResultSignals(mention_rank=3, cited=False),
        ResultSignals(mention_rank=None, cited=False),
        ResultSignals(mention_rank=None, cited=False),
    ]
    s = score_entity(signals)
    # mention_rate 0.5; rank factor (1 + 1/3)/2 = 0.6667; citation_rate 0.25
    assert s.mention_rate == 0.5
    assert s.citation_rate == 0.25
    assert s.result_count == 4
    assert s.score == round(100 * (0.6 * 0.5 + 0.25 * ((1 + 1 / 3) / 2) + 0.15 * 0.25), 2)
    assert s.score == 50.42


def test_perfect_and_zero_scores():
    assert score_entity([ResultSignals(1, True)] * 3).score == 100.0
    assert score_entity([ResultSignals(None, False)] * 3).score == 0.0
    assert score_entity([]).score == 0.0


def test_share_of_voice():
    sov = share_of_voice({"Smith": 6, "Rotman": 3, "Ivey": 1})
    assert sov == {"Smith": 60.0, "Rotman": 30.0, "Ivey": 10.0}
    assert share_of_voice({}) == {}
    assert share_of_voice({"Smith": 0}) == {}


def test_citation_categorization():
    brand = ["smith.queensu.ca"]
    comp = ["rotman.utoronto.ca", "ivey.uwo.ca"]
    assert categorize_domain("smith.queensu.ca", brand, comp) == "brand"
    assert categorize_domain("www.smith.queensu.ca", brand, comp) == "brand"
    assert categorize_domain("programs.smith.queensu.ca", brand, comp) == "brand"
    assert categorize_domain("rotman.utoronto.ca", brand, comp) == "competitor"
    assert categorize_domain("ft.com", brand, comp) == "other"
    assert categorize_domain("notsmith.queensu.ca", brand, comp) == "other"


def test_source_type_classification():
    assert classify_source_type("en.wikipedia.org") == "encyclopedia"
    assert classify_source_type("www.reddit.com") == "community"
    assert classify_source_type("youtube.com") == "video"
    assert classify_source_type("g2.com") == "review"
    assert classify_source_type("linkedin.com") == "social"
    # The long tail — real publishers — falls through to 'publisher'.
    assert classify_source_type("ft.com") == "publisher"
    assert classify_source_type("smith.queensu.ca") == "publisher"