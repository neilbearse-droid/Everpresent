"""The model each measured API engine is asked as, by the client's audience.

The API surfaces are proxies for consumer apps, so the model they call should
be the one a real user of that app gets. Which user depends on who the client
sells to (Tenant.audience): a consumer brand ("d2c") is seen through the free
app, a business ("b2b") through the paid tier its buyers are on. One toggle
per client picks the whole column; the plan no longer chooses models (M62).

This table is editorial, like the audience weights: no provider publishes
"what the free app serves today" over an API, so each row is pinned by hand,
dated and sourced. The staleness test fails once a pin is older than
STALE_AFTER_DAYS, so a pin cannot quietly outlive the product it describes.
To re-pin: check what each app serves on its free and paid tiers, update the
row, set as_of to today, add the price to engine/costs.py if the model is new,
and add a line to DECISIONS.md.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime

# audience -> the consumer tier it is seen through.
AUDIENCES: dict[str, str] = {"d2c": "free", "b2b": "paid"}
AUDIENCE_LABELS: dict[str, str] = {
    "d2c": "Consumer brand (free tier)",
    "b2b": "Business (paid tier)",
}
DEFAULT_AUDIENCE = "d2c"

# A pin older than this fails tests/test_consumer_models.py. 45 days is about
# one release cycle at the current pace; the failure message says what to do.
STALE_AFTER_DAYS = 45


@dataclass(frozen=True)
class EnginePin:
    free: str      # what the app's free tier serves
    paid: str      # what its entry paid tier serves by default
    as_of: str     # ISO date this row was last checked
    source: str    # what was read to pin it


CONSUMER_MODELS: dict[str, EnginePin] = {
    "openai_api": EnginePin(
        free="gpt-6-luna", paid="gpt-6-sol", as_of="2026-11-02",
        source=("ChatGPT has run GPT-6 by default since 2026-10-07: Luna on Free and Go, "
                "Sol on Plus and above (OpenAI's GPT-6 Sol and Luna post; third-party "
                "coverage of the 7 Oct switch). API ids gpt-6-luna / gpt-6-sol."),
    ),
    "claude_api": EnginePin(
        free="claude-sonnet-5-5", paid="claude-opus-5-5", as_of="2026-11-02",
        source=("claude.ai Free runs Sonnet 5.5 since 2026-09-28 (Anthropic's launch "
                "post); Pro and Team default to Opus 5.5 since 2026-09-22 (two "
                "third-party reports; Anthropic's page calls it the default)."),
    ),
    "gemini_api": EnginePin(
        free="gemini-3.5-flash-lite", paid="gemini-4-argon", as_of="2026-11-02",
        source=("Gemini app Free moved to an Auto setting that mostly serves 3.5 Flash-Lite "
                "on 2026-10-09 (third-party reports; Google has not said); AI Pro and "
                "Ultra get Gemini 4 Argon since 2026-10-13 (Gemini app release notes). "
                "Argon is outside the API free tier, so a free-tier key cannot run b2b."),
    ),
    "perplexity_api": EnginePin(
        free="perplexity/sonar", paid="perplexity/sonar", as_of="2026-11-02",
        source=("One Perplexity-native model on the Agent API: sonar-pro has no Agent slug "
                "and the presets run OpenAI models (DECISIONS M-notes, 2026-09-27). "
                "Pro Search cannot be reproduced over the API, so both tiers ask Sonar."),
    ),
    "meta_api": EnginePin(
        free="muse-spark-1.3", paid="muse-spark-1.3", as_of="2026-11-02",
        source="Muse Spark is the one model the Meta AI app serves (DECISIONS M36).",
    ),
}


def tier_for(audience: str | None) -> str:
    """'free' or 'paid'. An unknown or missing audience is read as the default."""
    return AUDIENCES.get(audience or DEFAULT_AUDIENCE, AUDIENCES[DEFAULT_AUDIENCE])


def model_for(surface: str, audience: str | None, default: str) -> str:
    """The model to ask `surface` as for a client of this audience, or the
    deployment's configured default when the surface has no pin."""
    pin = CONSUMER_MODELS.get(surface)
    if pin is None:
        return default
    return pin.paid if tier_for(audience) == "paid" else pin.free


def models_for(audience: str | None) -> dict[str, str]:
    """surface -> model for one audience (what the admin page shows per choice)."""
    tier = tier_for(audience)
    return {s: (p.paid if tier == "paid" else p.free) for s, p in CONSUMER_MODELS.items()}


def pins_status(today: date | None = None) -> list[dict]:
    """Every pin with its age, for the admin page and the staleness test."""
    today = today or datetime.now(UTC).date()
    out = []
    for surface, pin in CONSUMER_MODELS.items():
        age = (today - date.fromisoformat(pin.as_of)).days
        out.append({
            "surface": surface, "free": pin.free, "paid": pin.paid,
            "as_of": pin.as_of, "age_days": age, "stale": age > STALE_AFTER_DAYS,
            "source": pin.source,
        })
    return out
