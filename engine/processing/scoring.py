"""Visibility scoring (§6.4). v3-NATIVE IMPLEMENTATION, not a v1 port
(DECISIONS.md M3.1); tests/test_scoring.py pins the formula.

A result contributes to an entity's visibility through three signals:
whether the entity is mentioned at all, how early it appears relative to
other entities (rank), and whether the answer cites the entity's own
domains. Scores are 0–100 per (surface, persona segment, day) group:

    score = 100 * (0.60 * mention_rate
                 + 0.25 * mean(1/rank over results that mention the entity)
                 + 0.15 * citation_rate)
"""

from dataclasses import dataclass, field

SCORER_VERSION = "v3.0.0"

W_MENTION, W_RANK, W_CITATION = 0.60, 0.25, 0.15


@dataclass
class ResultSignals:
    """Per-result, per-entity presence signals, extracted by the caller."""

    mention_rank: int | None  # 1-based rank if mentioned, else None
    cited: bool  # any citation on the entity's own domains


@dataclass
class EntityScore:
    score: float
    mention_rate: float
    citation_rate: float
    result_count: int


@dataclass
class GroupScores:
    brand: EntityScore
    competitors: dict[str, EntityScore] = field(default_factory=dict)


def score_entity(signals: list[ResultSignals]) -> EntityScore:
    n = len(signals)
    if n == 0:
        return EntityScore(score=0.0, mention_rate=0.0, citation_rate=0.0, result_count=0)
    # rank is 1-based; filter ≥1 once so numerator and denominator agree (the
    # old `if s.mention_rank` in the numerator only, on top of the is-not-None
    # filter, would have understated the score for a stray rank 0) — §audit low.
    mentioned = [s for s in signals if s.mention_rank is not None and s.mention_rank >= 1]
    mention_rate = len(mentioned) / n
    rank_factor = (
        sum(1.0 / s.mention_rank for s in mentioned) / len(mentioned)  # pyright: ignore[reportOptionalOperand]
        if mentioned
        else 0.0
    )
    citation_rate = sum(1 for s in signals if s.cited) / n
    score = 100.0 * (W_MENTION * mention_rate + W_RANK * rank_factor + W_CITATION * citation_rate)
    return EntityScore(
        score=round(score, 2),
        mention_rate=round(mention_rate, 4),
        citation_rate=round(citation_rate, 4),
        result_count=n,
    )


def share_of_voice(entity_mention_counts: dict[str, int]) -> dict[str, float]:
    """Mentions per entity → percentage share; empty when nothing mentioned."""
    total = sum(entity_mention_counts.values())
    if total == 0:
        return {}
    return {
        entity: round(100.0 * count / total, 2)
        for entity, count in entity_mention_counts.items()
    }
