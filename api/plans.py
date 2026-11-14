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
    # Fan-out re-probe (§FANOUT_SCORECARD M25b). K = shards re-probed per parent
    # prompt; the per-run ceiling bounds the whole run regardless of K. 0 = the
    # map only (no re-probe spend). Sized from the cost model in DECISIONS.md
    # M25b: a Gemini re-probe is ~$0.14 (grounding bills per sub-query), an
    # OpenAI one ~$0.02–0.07, so these hold re-probe spend near 10% of price.
    # Command/Custom ceilings cut 75 -> 15 to control run cost (DECISIONS M52).
    shard_probes_per_prompt: int = 0
    shard_probes_per_run: int = 0
    # Repeated sampling (Mode A, generic cells only): answers to the same
    # question vary run to run, so each run takes this many samples of every
    # generic query x engine cell. The first sample asks the canonical text;
    # the extras rotate through the query's paraphrases, offset by run, so
    # over consecutive runs every wording is asked. Persona cells stay at 1.
    # See research "AEO deep dive" sampling design.
    samples_per_cell: int = 1
    # Natural search-routing probe (§AEO-plan M2): the share of queries that
    # also get an un-forced call on the engines that force search, so the
    # "what users see" rate has data. None = the deployment setting
    # (NATURAL_PROBE_FRACTION; 0.34 on Render). Diagnose and above probe a
    # third of the queries each run. The probed slice rotates by run, so at
    # three runs a week every question still gets an unforced answer weekly,
    # and whether a prompt triggers search doesn't move faster than that.
    # Probing every query every run (the earlier setting) cost about $0.03 per
    # query per run on OpenAI and $0.01 on Perplexity: three times the spend
    # for the same weekly coverage.
    natural_probe_fraction: float | None = None


# The share of queries Diagnose and above send unforced each run.
PAID_PLAN_PROBE_FRACTION = 0.34


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
        shard_probes_per_prompt=2, shard_probes_per_run=15, samples_per_cell=2,
        natural_probe_fraction=PAID_PLAN_PROBE_FRACTION,
    ),
    "command": PlanLimits(
        "Command", max_prompts=None, max_personas=None, max_engines=None,
        diagnosis=True, model_tier="premium", outcome=True,
        max_runs_per_day=None, monthly_price_usd=2900, max_locations=5,
        shard_probes_per_prompt=5, shard_probes_per_run=15, samples_per_cell=3,
        natural_probe_fraction=PAID_PLAN_PROBE_FRACTION,
    ),
    "custom": PlanLimits(
        "Custom", max_prompts=None, max_personas=None, max_engines=None,
        diagnosis=True, model_tier="configured", outcome=True,
        max_runs_per_day=None, monthly_price_usd=0, max_locations=None,
        shard_probes_per_prompt=5, shard_probes_per_run=15, samples_per_cell=3,
    ),
}

DEFAULT_PLAN = "custom"


def limits_for(plan: str | None) -> PlanLimits:
    return PLANS.get(plan or DEFAULT_PLAN, PLANS[DEFAULT_PLAN])


# When several engines must be dropped to fit max_engines, keep them in this
# canonical order rather than alphabetical: the most-used answer engines first.
# Ordered 31 Oct 2026 on Similarweb, Sept 2026 visits: ChatGPT 56%, Gemini 25%,
# Claude 10%, Perplexity under 1%; Google AI Overviews appear on roughly 40% of
# US searches (third-party trackers). An AI Overviews capture is also cheaper
# than a Perplexity call, so the reorder is cost-neutral.
ENGINE_PRIORITY: list[str] = [
    "openai_api", "gemini_api", "google_aio", "claude_api", "google_ai_mode",
    "perplexity_api", "chatgpt_web", "copilot_web", "meta_api", "perplexity_web",
    "gemini_web", "meta_muse",
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
    # One Perplexity-native model on the Agent API: `sonar-pro` has no slug
    # there, and the "presets" run OpenAI models (wrong engine to measure).
    "perplexity_api": {
        "economy": "perplexity/sonar", "standard": "perplexity/sonar",
        "premium": "perplexity/sonar",
    },
    "claude_api": {
        "economy": "claude-haiku-4-5-20251001",
        "standard": "claude-sonnet-4-6",
        "premium": "claude-sonnet-4-6",
    },
    # Gemini 3.x (2.5 Pro is deprecated for 2026-10-16). Gemini 4 "Argon":
    # announced 30 Sept; GA 13 Oct 2026 (API; AI Mode for paid tiers). The
    # tier re-pin is a separate decision (not this week).
    "gemini_api": {"economy": "gemini-3.5-flash-lite", "standard": "gemini-3.6-flash",
                   "premium": "gemini-3.1-pro-preview"},
    # Muse Spark is the model the Meta AI app serves, so every tier measures it.
    "meta_api": {"economy": "muse-spark-1.3", "standard": "muse-spark-1.3",
                 "premium": "muse-spark-1.3"},
}


def model_for(surface: str, tier: str, default: str) -> str:
    """The model to use for a surface under a plan's tier, or the configured
    default when the tier doesn't override it (e.g. the 'custom' plan)."""
    return MODEL_TIERS.get(surface, {}).get(tier, default)
