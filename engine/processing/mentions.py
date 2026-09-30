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


def _alias_matches(text: str, text_lower: str, alias: str) -> list[tuple[int, int]]:
    """All word-boundary (start, end) spans of `alias`. A single-word alias
    written as a proper noun ("Horizon", "Lovable") only matches where the text
    also capitalizes it, so ordinary words ("on the horizon", "a lovable UI")
    don't count as a brand. Multi-word and mixed-case aliases ("GoDaddy",
    "Hostinger Horizon") match case-insensitively, as before."""
    pattern = r"(?<![\w])" + re.escape(alias.lower()) + r"(?![\w])"
    proper_word = " " not in alias and alias[:1].isupper() and alias[1:] == alias[1:].lower()
    spans = []
    for m in re.finditer(pattern, text_lower):
        if proper_word and not text[m.start()].isupper():
            continue
        spans.append((m.start(), m.end()))
    return spans


def detect_mentions(
    text: str,
    brand_name: str,
    brand_aliases: list[str],
    competitors: list[tuple[int | None, str, list[str]]],
) -> list[DetectedMention]:
    """Finds the first occurrence of each entity (canonical name or any alias)
    and returns mentions ordered by position, rank assigned 1..n.

    Overlaps resolve longest-first across ALL entities: in "Hostinger Horizon"
    the longer competitor claims the span, so the shorter "Hostinger" isn't
    also counted there (it still counts where it appears on its own)."""
    text_lower = text.lower()
    entities: list[tuple[str, str, int | None, list[str]]] = [
        ("brand", brand_name, None, [brand_name, *brand_aliases])
    ]
    for competitor_id, name, aliases in competitors:
        entities.append(("competitor", name, competitor_id, [name, *aliases]))

    candidates: list[tuple[int, int, int, str]] = []  # (start, end, entity index, alias)
    for index, (_etype, _name, _cid, aliases) in enumerate(entities):
        for alias in set(a for a in aliases if a):
            for start, end in _alias_matches(text, text_lower, alias):
                candidates.append((start, end, index, alias))

    # Longest span first; an accepted span blocks any overlapping shorter one.
    candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
    claimed: list[tuple[int, int]] = []
    first: dict[int, tuple[int, str]] = {}
    for start, end, index, alias in candidates:
        if any(start < c_end and c_start < end for c_start, c_end in claimed):
            continue
        claimed.append((start, end))
        if index not in first or start < first[index][0]:
            first[index] = (start, alias)

    found: list[DetectedMention] = []
    for index, (position, alias) in first.items():
        entity_type, name, competitor_id, _aliases = entities[index]
        found.append(
            DetectedMention(
                entity_type=entity_type,
                entity_name=name,
                competitor_id=competitor_id,
                matched_alias=alias,
                position=position,
                rank=0,  # assigned below
                sentiment=_window_sentiment(text, position, len(alias)),
                context_snippet=_snippet(text, position, len(alias)),
            )
        )

    found.sort(key=lambda m: m.position)
    for rank, mention in enumerate(found, start=1):
        mention.rank = rank
    return found
