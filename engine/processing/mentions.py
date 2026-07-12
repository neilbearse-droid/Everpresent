"""Mention detection: brand + competitor aliases, position, sentiment,
context snippet (§6.4).

v3-NATIVE IMPLEMENTATION, not a v1 port — the v1 source was unavailable
(DECISIONS.md M3.1). tests/test_mentions.py is the regression set that pins
this behavior; if the v1 code surfaces, port it and validate against both
sets before swapping.

Sentiment is a deliberately simple window lexicon (positive/negative terms
near the mention). Upgrading it to a Haiku call through the §4 router is a
drop-in change once a tenant's governance approves utility models.
"""

import re
from dataclasses import dataclass

DETECTOR_VERSION = "v3.0.0"

_POSITIVE = {
    "best", "top", "leading", "strong", "strongest", "excellent", "renowned",
    "recommended", "recommend", "praised", "outstanding", "premier", "trusted",
    "popular", "well-regarded", "highly", "affordable", "innovative", "ideal",
}
_NEGATIVE = {
    "worst", "weak", "weakest", "poor", "poorly", "expensive", "avoid",
    "criticized", "criticised", "declining", "limited", "lacking", "slow",
    "complaints", "underwhelming", "outdated",
}

_SNIPPET_RADIUS = 120
_SENTIMENT_RADIUS = 80


@dataclass
class DetectedMention:
    entity_type: str  # "brand" | "competitor"
    entity_name: str  # canonical name, not the alias that matched
    competitor_id: int | None
    matched_alias: str
    position: int  # character offset of first occurrence
    rank: int  # 1-based order of first appearance among detected entities
    sentiment: str  # "positive" | "negative" | "neutral"
    context_snippet: str


def _first_match(text_lower: str, alias: str) -> int:
    """Word-boundary match; -1 if absent. Aliases are matched literally."""
    pattern = r"(?<![\w])" + re.escape(alias.lower()) + r"(?![\w])"
    found = re.search(pattern, text_lower)
    return found.start() if found else -1


def _window_sentiment(text: str, position: int, length: int) -> str:
    start = max(0, position - _SENTIMENT_RADIUS)
    window = text[start : position + length + _SENTIMENT_RADIUS].lower()
    words = set(re.findall(r"[a-z][a-z-]*", window))
    pos_hits = len(words & _POSITIVE)
    neg_hits = len(words & _NEGATIVE)
    if pos_hits > neg_hits:
        return "positive"
    if neg_hits > pos_hits:
        return "negative"
    return "neutral"


def _snippet(text: str, position: int, length: int) -> str:
    start = max(0, position - _SNIPPET_RADIUS)
    end = min(len(text), position + length + _SNIPPET_RADIUS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def detect_mentions(
    text: str,
    brand_name: str,
    brand_aliases: list[str],
    competitors: list[tuple[int | None, str, list[str]]],
) -> list[DetectedMention]:
    """Finds the first occurrence of each entity (canonical name or any
    alias — longest alias wins position ties) and returns mentions ordered by
    position, rank assigned 1..n."""
    text_lower = text.lower()
    entities: list[tuple[str, str, int | None, list[str]]] = [
        ("brand", brand_name, None, [brand_name, *brand_aliases])
    ]
    for competitor_id, name, aliases in competitors:
        entities.append(("competitor", name, competitor_id, [name, *aliases]))

    found: list[DetectedMention] = []
    for entity_type, name, competitor_id, aliases in entities:
        best_pos, best_alias = -1, ""
        for alias in sorted(set(a for a in aliases if a), key=len, reverse=True):
            pos = _first_match(text_lower, alias)
            if pos >= 0 and (best_pos < 0 or pos < best_pos):
                best_pos, best_alias = pos, alias
        if best_pos < 0:
            continue
        found.append(
            DetectedMention(
                entity_type=entity_type,
                entity_name=name,
                competitor_id=competitor_id,
                matched_alias=best_alias,
                position=best_pos,
                rank=0,  # assigned below
                sentiment=_window_sentiment(text, best_pos, len(best_alias)),
                context_snippet=_snippet(text, best_pos, len(best_alias)),
            )
        )

    found.sort(key=lambda m: m.position)
    for index, mention in enumerate(found, start=1):
        mention.rank = index
    return found
