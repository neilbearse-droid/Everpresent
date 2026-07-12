"""Cost estimation for measured-surface calls, used for runs.cost_usd and the
pre-dispatch spend-cap check (§9).

These are ESTIMATES for cap enforcement and reporting, not billing truth —
reconcile against the provider dashboard and update when prices move. Prices
in USD per 1M tokens; web search per 1k tool calls."""

# model prefix -> (input $/1M, output $/1M). Longest prefix wins so dated
# snapshots ("gpt-4o-2024-08-06") match their family.
OPENAI_TOKEN_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
}
OPENAI_WEB_SEARCH_PER_1K_CALLS = 10.00
_FALLBACK_TOKEN_PRICE = (2.50, 10.00)  # unknown model: assume gpt-4o-class


def estimate_openai_cost_usd(
    model: str, input_tokens: int, output_tokens: int, web_search_calls: int = 0
) -> float:
    price = _FALLBACK_TOKEN_PRICE
    best_len = -1
    for prefix, p in OPENAI_TOKEN_PRICES.items():
        if model.startswith(prefix) and len(prefix) > best_len:
            price, best_len = p, len(prefix)
    cost = (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000
    cost += web_search_calls * OPENAI_WEB_SEARCH_PER_1K_CALLS / 1_000
    return round(cost, 6)
