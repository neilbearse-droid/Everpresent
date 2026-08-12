# Fan-out Scorecard — Milestone Spec (build 2)

Status: **proposed**. Companion to the shipped reframed Overview (`engine_modes`).
This turns fan-out from a *map* into a *prioritized, longitudinal worklist*.

## 1. Why

When a retrieval engine (Gemini, Copilot, sometimes ChatGPT) answers a prompt,
it doesn't search the prompt — it **fans it out** into N sub-queries ("shards")
and competes each one separately. We already capture the shard *text* per prompt
(`Result.fanout_queries`, surfaced read-only in `fanout_report`). What we don't
yet have is **the brand's presence per shard**.

The deliverable is the difference between:
- Today: "Gemini fanned this into 18 sub-queries." (descriptive)
- Build 2: "You're **absent from 11 of the 18** shards Gemini issued — here are
  the 4 highest-yield misses and who's winning them." (prescriptive)

Nobody in the space is turning fan-out into a prioritized, tracked scorecard.
It's the strongest moat on the roadmap.

## 2. The hard part — per-shard presence

**Reality check (verified against the adapters).** We capture the shard *query
strings* (`Result.fanout_queries`, from Gemini's `webSearchQueries` and OpenAI's
fan-out) and the answer's citations/grounding — but grounding is attached at the
**answer level, not per shard**. No engine returns a clean "shard → its own
result/sources" mapping (`engine/retrievers/gemini_api.py`). So there is **no
free path to honest per-shard presence**: knowing a brand is cited *somewhere in
the answer* does not tell you it won *this shard*.

Consequence: the truthful per-shard scorecard is fundamentally a **re-probe**
feature. The three options:

- **A — Attribute answer-level citations onto shards (indicative only).** Map the
  parent answer's citations/mentions onto shards by topical overlap. Free, but
  fuzzy — must be labeled "indicative, not per-shard verified." Good enough to
  render the *map*, not to claim presence.
- **B — Re-probe every shard (rejected as default).** Run each shard as its own
  query, measure presence directly. True, but multiplies query volume by the
  fan-out factor (an 18-shard prompt = 18× the calls). Uncapped, that's a spend
  problem.
- **C — Hybrid, cost-bounded (ship).** Render the shard map + indicative
  attribution for free (option A), and **re-probe only the top-K highest-value
  shards** to get honest presence where it matters. "Highest-value" = the same
  `reach × loss` rank the UI shows: issued by ≥2 engines AND a competitor likely
  present AND brand not already confirmed present. Spend goes exactly where a
  HIGH-priority miss might live.

This reshapes the rollout (§9): the free phase ships the **map**, not presence;
honest presence arrives only with the re-probe phase.

## 3. Data model (migration M25)

Head is `f8a9b0c1d2e3` (M24) → new revision `M25`.

### 3.1 New table `fanout_shards`

```
FanoutShard
  id: int pk
  tenant_id: int fk tenants.id (index)
  run_id: int fk runs.id (index)          # the run that observed this fan-out
  parent_query_text: str (index)          # the tracked prompt this shard came from
  shard_text: str                         # the sub-query the engine issued
  shard_norm: str (index)                 # lower/trimmed, for dedup + trend join
  issuing_surfaces: list[str] (JSON)      # surfaces that issued this shard
  brand_present: bool | None              # None = unresolved
  winners: list[str] (JSON)               # competitors present in the shard answer
  source: str                             # "grounded" | "reprobed" | "unresolved"
  priority: str                           # "high" | "med" | "low"
  reach: int                              # # engines that issued it
  created_at: datetime
  __table_args__ = UniqueConstraint(tenant_id, run_id, parent_query_text, shard_norm)
```

Idempotent per (tenant, run, parent, shard_norm) — re-processing a run replaces,
never duplicates (mirror the `UntrackedMention` / rollup upsert pattern).

### 3.2 Re-probe results reuse the Result table

Add `ResultVariant.shard = "shard"`. **No DDL** — `results.variant` is a string
column (StrEnum), not a native PG enum, so this is a code-only enum addition
(unlike the copilot_web M20 case).

A re-probe writes a `Result(variant="shard", query_text=shard_text, ...)`, run
through the **existing** mention/citation extraction — so presence + winners come
from the same classifier we already trust. **Every competitive aggregation is
safe by construction**: `_latest_results_by_variant` and friends request
`search` / `natural` / `nosearch` explicitly and never ask for `shard`, so shard
probes cannot leak into visibility, SOV, engine_modes, or rollups. Add a coupling
test asserting `shard` is absent from every aggregation's variant filter.

## 4. Probe budget & governance

- **Plan-gated K** (shards re-probed per parent prompt), via `plans.py`:
  Starter → 0 (grounded-only), Growth → 5, Scale/Custom → 12. Log what was
  dropped when a prompt's shard count exceeds K (no silent truncation).
- **Global per-run ceiling** on shard probes, independent of K.
- **Spend cap**: shard probes are ordinary metered calls — they run through the
  existing `monthly_spend_cap_usd` accounting and stop when the cap trips,
  recording `blocked`, never silently skipped.
- **Governance**: re-probing is just more retrieval queries (no new LLM
  processing), so it does **not** require `ai_processing_approved`. Gate it behind
  a per-tenant `fanout_reprobe_enabled` flag (default off), same shape as
  `entity_extraction_enabled`, so it's opt-in and admin-visible.

## 5. Processing pipeline integration

In `processing_service`, after mention/citation extraction for a run:
1. Collect observed shards from `Result.fanout_queries` across the run's search
   results, deduped by `shard_norm`, union of issuing surfaces, excluding shards
   equal to the parent prompt.
2. Resolve grounded presence where available (Gemini/AIO grounding).
3. Rank unresolved shards by preliminary `reach × loss`; re-probe the top-K under
   the plan cap + spend cap; extract presence/winners.
4. Upsert `FanoutShard` rows; compute `priority`.

Runs in the worker, cost-bounded, idempotent — same contract as the rest of the
pipeline. Grounded-only tenants (K=0) still get a real (partial) scorecard.

## 6. Priority ranking

`priority = f(reach, loss)`:
- **HIGH** — reach ≥ 2 engines **and** brand absent **and** ≥1 competitor present.
- **MED** — brand absent (reach 1, or no competitor named).
- **LOW** — brand present, or shard is purely informational with no competitor.

Sort HIGH → MED → LOW, then by reach desc. HIGH misses are the content worklist.

## 7. API + UI

- `GET /api/tenant/fanout-scorecard?start&end` → extends `fanout_report`:
  ```
  { brand_name, observed,
    prompts: [ { query, reach_by_engine: {label: shard_count},
                 shards_total, shards_present, shards_absent,
                 shards: [ { text, issuing_surfaces, brand_present, winners,
                             source, priority } ] } ],
    coverage: { grounded, reprobed, unresolved } }   # honesty counters
  ```
- New **Fan-out** tab: per prompt, the `X / N shards name you` stat + the shard
  table from the approved mockup (shard · issued-by chips · You present/absent ·
  who won · priority), HIGH rows tinted. Feeds each HIGH miss into the existing
  content-draft generator so a miss becomes a corrective brief in one click.

## 8. Honesty rails (non-negotiable)

- **Coverage is uneven and shown.** Only some engines expose fan-out; Claude
  often doesn't search. Render "did not search" — never invent shards.
- **`source` per shard is visible** (grounded / reprobed / unresolved) so a
  client knows which presence calls are direct truth vs re-probed vs unknown.
- **Longitudinal by default.** Shards are keyed by `shard_norm` across runs, so
  the scorecard trends — shards you *win back* show up. Directly counters the
  "single snapshot, not repeated" weakness of the market critique.
- **No silent caps.** `log()` every shard dropped by K or the spend cap.

## 9. Rollout (phased)

- **M25a — shard map (free, no spend).** Extend `fanout_report` into a scorecard
  read (reach-by-engine, shard list, present/absent counts via *indicative*
  answer-level attribution) + nav tab + page. Honest labeling: this ships the
  **map**, not verified per-shard presence — every attributed cell is marked
  indicative. No schema, no `FanoutShard`, no re-probe.
- **M25b — bounded re-probe (honest presence).** Schema (`FanoutShard`, M25) +
  `ResultVariant.shard`, pipeline harvest + plan-gated re-probe of top-K,
  spend-cap integration, `fanout_reprobe_enabled` admin toggle, coupling test
  that `shard` never enters competitive aggregations. This is where true
  per-shard presence + `reach × loss` priority arrive.
- **M25c — close the loop.** "Generate corrective brief" per HIGH miss (reuse
  `content_service`), and trend deltas on the scorecard.

## 10. Estimate & risks

- **Size:** ~M-sized. M25a is the bulk of the value at low risk; M25b carries the
  spend/pollution risk and is where the coupling test + caps matter most.
- **Risks:**
  - *Shard extraction fidelity* — engines expose fan-out inconsistently; grounded
    coverage may be thin for some tenants. Mitigation: `source`/coverage counters
    make partial coverage honest rather than hidden.
  - *Re-probe cost drift* — mitigated by plan-gated K + global ceiling + spend cap.
  - *Aggregation pollution* — mitigated structurally (variant filter) + the
    coupling test.
- **Open questions:**
  1. Default K per plan tier — needs a cost model pass against real fan-out
     counts (Gemini's tail can be 15–18).
  2. Winner attribution on re-probed shards — reuse competitor mention classifier
     (preferred) vs a lighter heuristic.
  3. Audience-weighted composite (deferred from build 1) — fold the per-tenant
     engine weighting in here or as its own small milestone.
