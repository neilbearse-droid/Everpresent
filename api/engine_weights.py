"""Audience weights for the pooled headline.

The per-engine rates are the measurement. The pooled "overall" rate used to
give every answer one vote, so an engine with 1% of the audience counted as
much as ChatGPT. It now weights each engine family by its share of the
audience: `overall = Σ weight × rate / Σ weight` over the families the client
measures. A family with no answers drops out of the denominator; weight 0
means measured and shown per engine, but not pooled.

The default table is a judgement anchored in two panels (Similarweb visits
and StatCounter referral clicks, both September 2026). Neither panel covers
Google's AI Overviews or AI Mode, which appear on a large share of searches,
so their rows are placed by judgement and say so. A client can override the
table (B2B software leans Claude and Perplexity; consumer brands the other
way); every change is dated and becomes a note on the pooled series.
"""

from typing import Any

WEIGHTS_DATE = "2026-11-01"
WEIGHTS_SOURCE = (
    "Similarweb visits and StatCounter referral clicks, September 2026; Google's AI "
    "surfaces placed by judgement, since neither panel covers them"
)

# family -> weight (0-100; only the ratios matter).
DEFAULT_ENGINE_WEIGHTS: dict[str, int] = {
    "chatgpt": 40,
    "google_aio": 20,
    "gemini": 12,
    "google_ai_mode": 10,
    "claude": 8,
    "copilot": 4,
    "perplexity": 3,
    "meta": 3,
}

FAMILY_LABELS: dict[str, str] = {
    "chatgpt": "ChatGPT",
    "google_aio": "Google AI Overviews",
    "gemini": "Gemini",
    "google_ai_mode": "Google AI Mode",
    "claude": "Claude",
    "copilot": "Microsoft Copilot",
    "perplexity": "Perplexity",
    "meta": "Meta AI",
}

# Surfaces that measure the same engine share its weight: their answers are
# pooled into one family cell first, so measuring ChatGPT twice (API and web)
# doesn't double its vote.
FAMILY_OF: dict[str, str] = {
    "openai_api": "chatgpt",
    "chatgpt_web": "chatgpt",
    "gemini_api": "gemini",
    "gemini_web": "gemini",
    "google_aio": "google_aio",
    "google_ai_mode": "google_ai_mode",
    "claude_api": "claude",
    "copilot_web": "copilot",
    "perplexity_api": "perplexity",
    "perplexity_web": "perplexity",
    "meta_api": "meta",
    "meta_muse": "meta",
}


def family_of(surface: str) -> str:
    return FAMILY_OF.get(surface, surface)


def engine_weights(tenant: Any) -> dict[str, int]:
    """The default table with the tenant's override on top. Unknown families
    are ignored; values are clipped to 0-100."""
    weights = dict(DEFAULT_ENGINE_WEIGHTS)
    override = getattr(tenant, "engine_weights", None) or {}
    for family, value in override.items():
        if family in weights:
            try:
                weights[family] = max(0, min(100, int(value)))
            except (TypeError, ValueError):
                continue
    return weights


def weight_lines(weights: dict[str, int], families: set[str]) -> list[dict]:
    """How the pooled rate is weighted, over the families with answers, for
    display: label, weight and share of the pooled total, heaviest first.
    Unknown families (a surface with no entry) count as weight 0."""
    present = {f: weights.get(f, 0) for f in families}
    total = sum(present.values())
    return [
        {
            "family": f,
            "label": FAMILY_LABELS.get(f, f),
            "weight": w,
            "share_pct": round(100 * w / total, 1) if total else 0.0,
            "pooled": w > 0,
        }
        for f, w in sorted(present.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# Repeated sampling follows the audience. The plan's samples_per_cell is what
# the heaviest family gets; lighter families take fewer, down to one, because
# the headline's precision lives in the engines most people use. Engines that
# cost next to nothing keep the full count regardless of weight.
CHEAP_SURFACES: frozenset[str] = frozenset({"perplexity_api"})
# Engines whose answers cost several times the others'. Gemini 3 bills search
# grounding per sub-query it fans out into, and it fans out widely (about
# $0.14 an answer, DECISIONS.md M25b), so it needs twice the audience weight
# for each extra sample.
COSTLY_SURFACES: frozenset[str] = frozenset({"gemini_api"})


def samples_for_surface(surface: str, max_samples: int, weights: dict[str, int]) -> int:
    """How many samples of each generic cell this surface gets per run.

    weight >= 20: the plan's count; weight >= 10: one fewer; below: one.
    Cheap surfaces always get the plan's count. Costly ones need twice the
    weight for each step (>= 40 and >= 20), so a client that leans on such
    an engine can still buy its full count by raising the weight. Never
    below one."""
    n = max(1, int(max_samples))
    if surface in CHEAP_SURFACES:
        return n
    w = weights.get(family_of(surface), 0)
    if surface in COSTLY_SURFACES:
        w = w / 2
    if w >= 20:
        return n
    if w >= 10:
        return max(1, n - 1)
    return 1
