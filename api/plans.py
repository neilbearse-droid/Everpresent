"""Subscription plans (pricing tiers, §pricing-model).

A plan caps the run matrix — prompts, personas, engines — toggles the
dual-query diagnosis (the expensive search-vs-training twin), and selects the
model tier per measured surface. Enforced in the run pipeline so spend tracks
the plan the tenant pays for. 'custom' is uncapped and uses the deployment's
configured models (the pre-plan behaviour), for enterprise/legacy tenants.

The per-tier models are real consumer models; the §4 runtime-model ban is
enforced by the policy test, which scans this file for forbidden substrings.
"""

from dataclasses import dataclass
from enum import StrEnum


class PlanTier(StrEnum):
    monitor = "monitor"
    diagnose = "diagnose"
    command = "command"
    custom = "custom"


@dataclass(frozen=True)
class PlanLimits:
    label: str
    max_prompts: int | None      # None = uncapped
    max_personas: int | None
    max_engines: int | None
    diagnosis: bool              # emit the search-disabled dual-query twin
    model_tier: str              # economy | standard | premium | configured
    outcome: bool                # GA4 outcome attribution available
    max_runs_per_day: int | None  # scheduled-run frequency cap (None = uncapped)
    monthly_price_usd: int
    # Location-based queries (§SCRAPING_V3 Part 2). Mode B fans out over this
    # many active locations; volume = queries × surfaces × locations, so this
    # is the multi-location cost gate. 1 = single (default) location only.
    max_locations: int | None = 1


PLANS: dict[str, PlanLimits] = {
    "monitor": PlanLimits(
        "Monitor", max_prompts=25, max_personas=1, max_engines=3,
        diagnosis=False, model_tier="economy", outcome=False,
        max_runs_per_day=1, monthly_price_usd=149, max_locations=1,
    ),
    "diagnose": PlanLimits(
        "Diagnose", max_prompts=50, max_personas=2, max_engines=4,
        diagnosis=True, model_tier="standard", outcome=True,
        max_runs_per_day=1, monthly_price_usd=549, max_locations=1,
    ),
    "command": PlanLimits(
        "Command", max_prompts=None, max_personas=None, max_engines=None,
        diagnosis=True, model_tier="premium", outcome=True,
        max_runs_per_day=None, monthly_price_usd=2900, max_locations=5,
    ),
    "custom": PlanLimits(
        "Custom", max_prompts=None, max_personas=None, max_engines=None,
        diagnosis=True, model_tier="configured", outcome=True,
        max_runs_per_day=None, monthly_price_usd=0, max_locations=None,
    ),
}

DEFAULT_PLAN = "custom"


def limits_for(plan: str | None) -> PlanLimits:
    return PLANS.get(plan or DEFAULT_PLAN, PLANS[DEFAULT_PLAN])


# When several engines must be dropped to fit max_engines, keep them in this
# canonical order (the most-used answer engines first) rather than alphabetical.
ENGINE_PRIORITY: list[str] = [
    "openai_api", "perplexity_api", "claude_api", "gemini_api",
    "chatgpt_web", "perplexity_web", "copilot_web", "google_aio", "gemini_web",
]


def cap_engines(surfaces: list[str], max_engines: int | None) -> list[str]:
    if max_engines is None:
        return surfaces
    ordered = sorted(surfaces, key=lambda s: ENGINE_PRIORITY.index(s)
                     if s in ENGINE_PRIORITY else len(ENGINE_PRIORITY))
    return ordered[:max_engines]


# Per-surface model by tier. Overrides the configured default so a plan's
# model_tier actually moves cost. 'configured' (custom plan) falls back to the
# deployment's settings. All real consumer models — no build-time models.
MODEL_TIERS: dict[str, dict[str, str]] = {
    "openai_api": {"economy": "gpt-5-mini", "standard": "gpt-5.6-terra", "premium": "gpt-5.6-sol"},
    "perplexity_api": {"economy": "sonar", "standard": "sonar", "premium": "sonar-pro"},
    "claude_api": {
        "economy": "claude-haiku-4-5-20251001",
        "standard": "claude-sonnet-4-6",
        "premium": "claude-sonnet-4-6",
    },
    "gemini_api": {"economy": "gemini-2.0-flash", "standard": "gemini-2.5-flash",
                   "premium": "gemini-2.5-pro"},
}


def model_for(surface: str, tier: str, default: str) -> str:
    """The model to use for a surface under a plan's tier, or the configured
    default when the tier doesn't override it (e.g. the 'custom' plan)."""
    return MODEL_TIERS.get(surface, {}).get(tier, default)
