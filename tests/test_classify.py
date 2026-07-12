"""Golden regression set for the dual-query diffing classifier
(DECISIONS.md M3.1)."""

from engine.processing.classify import (
    CLASSIFIER_VERSION,
    WebSearchSignals,
    classify_web_search_likelihood,
    compute_divergence,
)


def test_buckets():
    cases = [
        # (web_search_calls, citations, divergence) -> bucket
        ((1, 3, 0.80), "very_likely"),
        ((2, 1, 0.45), "very_likely"),  # threshold inclusive
        ((1, 2, 0.10), "likely"),  # searched+cited, but same answer anyway
        ((1, 0, 0.20), "possible"),  # searched, nothing usable cited
        ((0, 0, 0.70), "possible"),  # diverged without search signal
        ((0, 0, 0.05), "unlikely"),  # training answers this
    ]
    for (calls, cites, div), expected in cases:
        signals = WebSearchSignals(calls, cites, div)
        assert classify_web_search_likelihood(signals) == expected, signals


def test_divergence_bounds_and_normalization():
    assert compute_divergence("same answer", "same  answer") == 0.0
    assert compute_divergence("", "") == 0.0
    assert compute_divergence("alpha beta gamma", "delta epsilon zeta") > 0.8
    mid = compute_divergence(
        "The best MBA is Smith, followed by Rotman.",
        "The best MBA is Rotman, followed by Ivey.",
    )
    assert 0.1 < mid < 0.6


def test_version_is_pinned():
    assert CLASSIFIER_VERSION == "v3.0.0"
