"""GA4 AI-referral attribution (panel #6 / Outcome).

Answer engines increasingly stamp `utm_source` on their citation links
(ChatGPT → `chatgpt.com`), but not on every click, and some (Perplexity) often
arrive as a plain referral. GA4's `sessionSource` dimension resolves to the
`utm_source` when present and the referrer host otherwise — so classifying that
one dimension against the AI token set catches both in a single pass.

Pure functions only: request building and response parsing are fixture-tested;
the authenticated fetch lives in worker/ga4_pull.py.
"""

from typing import Any

# Canonical engine -> substrings that identify it in a GA4 source string.
# Order matters: earlier, more specific tokens win. Bare "google" is NOT here —
# that's organic search, not Gemini.
AI_SOURCE_TOKENS: list[tuple[str, tuple[str, ...]]] = [
    ("ChatGPT", ("chatgpt", "chat.openai", "openai")),
    ("Perplexity", ("perplexity",)),
    ("Claude", ("claude", "anthropic")),
    ("Gemini", ("gemini", "bard")),
    ("Copilot", ("copilot", "bing.com/chat", "bingchat")),
    ("DeepSeek", ("deepseek",)),
    ("Grok", ("grok",)),
    ("Meta AI", ("meta.ai",)),
    ("You.com", ("you.com",)),
]


def classify_source(source: str) -> str | None:
    """Map a GA4 session source (utm_source or referrer host) to an answer
    engine, or None if it isn't AI traffic."""
    s = (source or "").strip().lower()
    if not s:
        return None
    for engine, tokens in AI_SOURCE_TOKENS:
        if any(tok in s for tok in tokens):
            return engine
    return None


def build_report_request(start_date: str, end_date: str) -> dict[str, Any]:
    """A GA4 Data API runReport body: daily sessions + key events by source.
    Dates are ISO (YYYY-MM-DD) or GA4 relative tokens (e.g. '28daysAgo')."""
    return {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "dimensions": [{"name": "date"}, {"name": "sessionSource"}],
        "metrics": [{"name": "sessions"}, {"name": "keyEvents"}],
        "limit": 100000,
        "returnPropertyQuota": False,
    }


def _iso_date(ga4_date: str) -> str:
    """GA4 returns the `date` dimension as YYYYMMDD; normalize to YYYY-MM-DD."""
    if len(ga4_date) == 8 and ga4_date.isdigit():
        return f"{ga4_date[:4]}-{ga4_date[4:6]}-{ga4_date[6:]}"
    return ga4_date


def _to_int(value: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def parse_report(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Bucket a runReport response into per-(date, engine) AI-referral rows,
    summing sources that map to the same engine and dropping non-AI traffic."""
    dim_names = [h.get("name") for h in payload.get("dimensionHeaders", [])]
    metric_names = [h.get("name") for h in payload.get("metricHeaders", [])]
    try:
        date_i = dim_names.index("date")
        source_i = dim_names.index("sessionSource")
    except ValueError:
        return []
    sess_i = metric_names.index("sessions") if "sessions" in metric_names else None
    conv_i = metric_names.index("keyEvents") if "keyEvents" in metric_names else None

    agg: dict[tuple[str, str], dict[str, int]] = {}
    for row in payload.get("rows", []) or []:
        dims = [d.get("value", "") for d in row.get("dimensionValues", [])]
        mets = [m.get("value", "0") for m in row.get("metricValues", [])]
        engine = classify_source(dims[source_i] if source_i < len(dims) else "")
        if engine is None:
            continue
        key = (_iso_date(dims[date_i]), engine)
        entry = agg.setdefault(key, {"sessions": 0, "conversions": 0})
        if sess_i is not None and sess_i < len(mets):
            entry["sessions"] += _to_int(mets[sess_i])
        if conv_i is not None and conv_i < len(mets):
            entry["conversions"] += _to_int(mets[conv_i])

    return [
        {"date": date, "engine": engine, "sessions": v["sessions"],
         "conversions": v["conversions"]}
        for (date, engine), v in sorted(agg.items())
    ]
