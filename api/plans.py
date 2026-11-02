"""Subscription plans (pricing tiers, §pricing-model).

A plan caps the run matrix — prompts, personas, engines — and toggles the
dual-query diagnosis (the expensive search-vs-training twin). Enforced in the
run pipeline so spend tracks the plan the tenant pays for. 'custom' is
uncapped, for enterprise/legacy tenants.

Which model each API engine is asked as is NOT a plan choice: it follows the
client's audience (Tenant.audience -> api.consumer_models), so a plan moves
how much is measured, never which product is measured (M62).
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
    # (NATURAL_PROBE_FRACTION; 0.34 on Render). Diagnose and above probe every
    # query so the unforced series has the headline's n. Cost: about $0.03 per
    # query per run on OpenAI and $0.01 on Perplexity, so roughly $20-25 a
    # month for 50 questions at 3x/week.
    natural_probe_fraction: float | None = None


PLANS: dict[str, PlanLimits] = {
    "monitor": PlanLimits(
        "Monitor", max_prompts=25, max_personas=1, max_engines=3,
        diagnosis=False, outcome=False,
        max_runs_per_day=1, monthly_price_usd=149, max_locations=1,
    ),
    "diagnose": PlanLimits(
        "Diagnose", max_prompts=50, max_personas=2, max_engines=4,
        diagnosis=True, outcome=True,
        max_runs_per_day=1, monthly_price_usd=549, max_locations=1,
        shard_probes_per_prompt=2, shard_probes_per_run=15, samples_per_cell=2,
        natural_probe_fraction=1.0,
    ),
    "command": PlanLimits(
        "Command", max_prompts=None, max_personas=None, max_engines=None,
        diagnosis=True, outcome=True,
        max_runs_per_day=None, monthly_price_usd=2900, max_locations=5,
        shard_probes_per_prompt=5, shard_probes_per_run=15, samples_per_cell=3,
        natural_probe_fraction=1.0,
    ),
    "custom": PlanLimits(
        "Custom", max_prompts=None, max_personas=None, max_engines=None,
        diagnosis=True, outcome=True,
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
