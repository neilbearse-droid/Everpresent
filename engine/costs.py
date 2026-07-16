"""Cost estimation for measured-surface calls, used for runs.cost_usd and the
pre-dispatch spend-cap check (§9).

These are ESTIMATES for cap enforcement and reporting, not billing truth —
reconcile against the provider dashboard and update when prices move. Prices
in USD per 1M tokens; web search per 1k tool calls."""

# model prefix -> (input $/1M, output $/1M). Longest prefix wins so dated
# snapshots ("gpt-4o-2024-08-06") and family tiers ("gpt-5.6-terra") match
# correctly. Update as OpenAI's pricing ladder moves.
OPENAI_TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    # GPT-5 range (2026). 5.6 ships as three tiers; the bare "gpt-5.6" alias
    # is Sol. Longest-prefix match keeps the tiers distinct.
    "gpt-5.6-luna": (1.00, 6.00),
    "gpt-5.6-terra": (2.50, 15.00),
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.6": (5.00, 30.00),
    "gpt-5.5": (5.00, 30.00),
    "gpt-5.4": (2.50, 15.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
}
OPENAI_WEB_SEARCH_PER_1K_CALLS = 10.00
_FALLBACK_TOKEN_PRICE = (2.50, 10.00)  # unknown model: assume gpt-4o-class


def _token_cost(
    prices: dict[str, tuple[float, float]],
    fallback: tuple[float, float],
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    price = fallback
    best_len = -1
    for prefix, p in prices.items():
        if model.startswith(prefix) and len(prefix) > best_len:
            price, best_len = p, len(prefix)
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000


def estimate_openai_cost_usd(
    model: str, input_tokens: int, output_tokens: int, web_search_calls: int = 0
) -> float:
    cost = _token_cost(
        OPENAI_TOKEN_PRICES, _FALLBACK_TOKEN_PRICE, model, input_tokens, output_tokens
    )
    cost += web_search_calls * OPENAI_WEB_SEARCH_PER_1K_CALLS / 1_000
    return round(cost, 6)


# Perplexity Sonar (§6.1). Token prices per 1M; plus a per-request search fee.
PERPLEXITY_TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "sonar-reasoning-pro": (2.00, 8.00),
    "sonar-reasoning": (1.00, 5.00),
    "sonar-pro": (3.00, 15.00),
    "sonar": (1.00, 1.00),
}
PERPLEXITY_SEARCH_PER_1K = 5.00
_PERPLEXITY_FALLBACK = (1.00, 1.00)


def estimate_perplexity_cost_usd(
    model: str, input_tokens: int, output_tokens: int, web_search_calls: int = 0
) -> float:
    cost = _token_cost(
        PERPLEXITY_TOKEN_PRICES, _PERPLEXITY_FALLBACK, model, input_tokens, output_tokens
    )
    cost += web_search_calls * PERPLEXITY_SEARCH_PER_1K / 1_000
    return round(cost, 6)


# Anthropic Claude (§6.1). Token prices per 1M; web search $10 / 1k.
ANTHROPIC_TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku": (1.00, 5.00),
    "claude-opus": (15.00, 75.00),
    "claude-sonnet": (3.00, 15.00),
}
ANTHROPIC_WEB_SEARCH_PER_1K = 10.00
_ANTHROPIC_FALLBACK = (3.00, 15.00)


def estimate_anthropic_cost_usd(
    model: str, input_tokens: int, output_tokens: int, web_search_calls: int = 0
) -> float:
    cost = _token_cost(
        ANTHROPIC_TOKEN_PRICES, _ANTHROPIC_FALLBACK, model, input_tokens, output_tokens
    )
    cost += web_search_calls * ANTHROPIC_WEB_SEARCH_PER_1K / 1_000
    return round(cost, 6)


# Google Gemini (§6.1). Token prices per 1M; grounding billed per 1k requests.
GEMINI_TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash": (0.10, 0.40),
}
GEMINI_GROUNDING_PER_1K = 35.00
_GEMINI_FALLBACK = (0.30, 2.50)


def estimate_gemini_cost_usd(
    model: str, input_tokens: int, output_tokens: int, web_search_calls: int = 0
) -> float:
    cost = _token_cost(
        GEMINI_TOKEN_PRICES, _GEMINI_FALLBACK, model, input_tokens, output_tokens
    )
    cost += web_search_calls * GEMINI_GROUNDING_PER_1K / 1_000
    return round(cost, 6)
