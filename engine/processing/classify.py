"""Query Intelligence: the dual-query diffing classifier (§1, §6.1).

Each query runs twice on the same persona — web search enabled and disabled.
The diff between the two answers, plus the enabled call's tool activity, is
what separates "the surface actually retrieves for this query" from "the
model answers from training". Buckets:

  very_likely  searched, cited sources, and the answer materially diverges
               from the no-search answer — retrieval is doing real work
  likely       searched with citations, but the answers barely diverge —
               retrieval decorates an answer the model already had
  possible     searched without usable citations, or diverged without search
               signal (retrieval influence is ambiguous)
  unlikely     did not search even though it could — training answers this

v3-NATIVE IMPLEMENTATION, not a v1 port (DECISIONS.md M3.1); the bucket
names and thresholds are pinned by tests/test_classify.py as the new
regression set."""

from dataclasses import dataclass
from difflib import SequenceMatcher

CLASSIFIER_VERSION = "v3.0.0"

DIVERGENCE_MATERIAL = 0.45  # above this, the two answers are substantially different

BUCKETS = ("very_likely", "likely", "possible", "unlikely")


@dataclass
class WebSearchSignals:
    web_search_calls: int
    citation_count: int
    divergence: float  # 0.0 (identical answers) .. 1.0 (nothing in common)


def compute_divergence(search_text: str, nosearch_text: str) -> float:
    """1 - token-level similarity; deterministic and cheap. Token-level (not
    character-level) so completely different answers score near 1.0 instead
    of being credited for shared letters."""
    a = search_text.lower().split()
    b = nosearch_text.lower().split()
    if not a and not b:
        return 0.0
    # autojunk=False: answers can exceed the 200-element autojunk threshold, and
    # junking common tokens would depress .ratio() for long answers, pushing
    # divergence up purely as a function of length (§audit low).
    return round(1.0 - SequenceMatcher(None, a, b, autojunk=False).ratio(), 4)


def classify_web_search_likelihood(signals: WebSearchSignals) -> str:
    searched = signals.web_search_calls > 0
    cited = signals.citation_count > 0
    diverged = signals.divergence >= DIVERGENCE_MATERIAL
    if searched and cited and diverged:
        return "very_likely"
    if searched and cited:
        return "likely"
    if searched or diverged:
        return "possible"
    return "unlikely"
