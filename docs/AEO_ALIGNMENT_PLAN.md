# EverPresent — AEO Alignment Build Plan

**Purpose.** Bring EverPresent's measurement and recommendation layers into line
with the July 2026 deep-research brief on how LLM search actually works
(`llmsearchaeoreport` — the source of truth for the "why" behind each item).
This document is a self-contained handoff: an implementing agent should be able
to execute it item by item without the originating conversation.

## Implementation status (updated)

**Shipped:** all six MAJOR items — M1 fan-out, M2 natural routing, M3 CSR
audit, M4 accuracy, M5 citability, M6 consulted sources — plus minors m1–m5.
Migrations M13–M16 (single head `d0e1f2a3b4c5`). Suite 162 → 191 passing.

**Remaining (optional tail):** m6 (new engine surfaces Copilot/Meta/Grok —
large, needs new adapters + cost fns), m7 (model-release re-baseline flag —
needs per-result model history), m8 (OpenAI licensed-feed `oai-*` labels —
needs a live-API response to confirm shape). None blocks the engagement.

---

**Framing.** The report *validates* EverPresent's core architecture — the
two-mode design (API vs. consumer web), the search/nosearch dual-query diff
(= the parametric-vs-retrieval distinction), structured citation parsing, the
Access Audit, Power Pages / third-party targeting, prominence, stability, and
GA4 outcomes. **Do not rebuild those.** Everything below is refinement and
extension.

---

## 0. Repo orientation & conventions (read first)

- **Backend:** FastAPI + SQLModel + Alembic (Postgres prod, SQLite tests).
  Engine (`engine/`) is pure retrieval/parsing/cost; API (`api/`) is
  request-shaped; the worker (`worker/`) is the only place they meet a DB
  session and a provider key.
- **Frontend:** Next.js 15 App Router, Tailwind 4, Clerk. Server pages fetch
  via `app/src/lib/api.ts` (`apiFetch`).
- **Migrations:** current head is `f6a7b8c9d0e1` (M12). New migrations chain
  from there (M13, M14, …). Native Postgres enums need
  `ALTER TYPE … ADD VALUE` inside `op.get_context().autocommit_block()`; SQLite
  is a no-op (values are plain strings). See
  `alembic/versions/f6a7b8c9d0e1_m12_scraping_v3.py` for the pattern.
- **Runtime-model policy (CRITICAL):** `tests/test_llm_policy.py` scans
  `.env*`, `api/**`, `worker/**`, `engine/**` for banned model-family
  substrings. Never write those substrings (or a build-time-only model id) in
  those paths, including comments/docstrings. Model tiers live in
  `api/plans.py::MODEL_TIERS` — all real consumer models.
- **Verify before every commit:**
  ```
  cd /home/user/Everpresent && python -m pytest -q
  python -m ruff check api/ worker/ engine/ tests/
  cd app && npx tsc --noEmit
  # for a new migration, sanity-check offline SQL:
  python -m alembic upgrade <prev>:<new> --sql
  ```
- **Branch:** `claude/everpresent-v3-rebuild-wy4ybi`. Commit in the established
  style; trailers `Co-Authored-By: …` and `Claude-Session: …`. Never put a
  model id in a commit/PR/code artifact.
- **Baseline before starting:** 162 tests passing, ruff + tsc clean.

## Recommended sequence

Front-load cheap, high-impact, no-new-data-dependency work:

**M3 → M5 → M1 → M6 → M4 → M2**, then minors **m1–m8** as they touch adjacent
code. Rationale: M3 (JS/CSR audit) and M5 (citability upgrade) improve every
existing client immediately with no new inputs; M1/M6 enrich data already
flowing; M4/M2 need a decision + new inputs (below).

## Decisions required before M2 and M4

- **D1 (blocks M2 — natural routing):** EverPresent forces web search
  (`tool_choice`) to guarantee citations, which overrides the router so we
  can't see whether a buyer's prompt would *naturally* trigger search (~31% are
  answered from weights; the report calls testing this "step one"). Options:
  (a) add a third `natural` variant (tool offered, not forced) run for every
  query — ~+1 API call/query cost; (b) forced-only, with a periodic sampled
  natural probe on a subset. **Recommended default:** (b) — a sampled probe,
  configurable, to bound cost. Implement M2 behind this decision.
- **D2 (blocks M4 — accuracy):** factual-accuracy detection needs a per-tenant
  **fact sheet** (accreditations, pricing, exec names, coverage terms) as
  ground truth. Confirm this can be collected at onboarding before building the
  checker. **Recommended default:** model a `BrandFact` table and a simple
  admin CRUD; the checker degrades to "no facts on file" when empty.

---

# MAJOR items

## M3 — JavaScript-rendering / CSR dependency audit

**Why.** The report's most repeated technical finding: *no major AI crawler
renders JavaScript; a client-side-rendered SPA is a blank page to ChatGPT,
Claude, and Perplexity* (§2.3 Pillar A). Exceptions: Gemini (Googlebot
rendering) and Applebot. This is a frequent, high-severity defect that silently
zeroes a brand's retrieval presence.

**Current state.** `worker/page_crawl.py` + `engine/audit/presence.py`
(`crawl_page`, `extract_features`) fetch **raw HTML** and fingerprint it, but
never *flag* a page whose content only materializes after JS. `engine/audit/
access.py` audits robots/UA but not rendering.

**Change.**
- `engine/audit/access.py` (or a new `engine/audit/rendering.py`): add a
  raw-HTML render-dependency check for the homepage + a sample of priority
  URLs. Heuristics on the raw document: near-empty `<body>` text with a large
  JS payload; a root mount node (`<div id="root">` / `<div id="__next">`) with
  no server-rendered content inside; main content word-count below a threshold
  while `<script>` bytes dominate; presence of `<noscript>` "enable JavaScript"
  copy. Grade `pass` (content in raw HTML) / `warn` (partial) / `fail` (shell
  only). Verify against **view-source**, not a headless render.
- Surface in the Access Audit payload + admin panel: a per-URL "AI-readable /
  CSR-blocked" verdict with the one-line fix ("server-side render or pre-render
  revenue content; verify schema/canonicals/meta live in raw HTML").
- Also assert schema/canonical/meta presence in *raw* HTML specifically (they
  are worthless if JS-injected).

**Tests.** `tests/test_access_audit.py` (extend) or new
`tests/test_rendering_audit.py`: raw HTML with real content → pass; a bare SPA
shell (`<div id="__next"></div>` + bundle script) → fail; partial → warn.

**Acceptance.** Access Audit reports a rendering verdict per audited URL;
admin renders it; SPA shells are flagged `fail` with the fix text.
**Effort:** M.

## M5 — Citability fingerprint upgrade to Tier-1 evidence

**Why.** The peer-reviewed GEO study (Princeton/GT/AI2/IIT-D, KDD 2024) and
Semrush/Indig data rank the levers that actually move citation: **quotations
from credible sources (~41%)**, **statistics / data-point density (~30–40%; 19+
discrete data points → 2–3× citations)**, **citing named sources (~115% for
non-#1 pages)**, a **40–60 word answer capsule under a question-format H2**,
**front-loading** (44% of citations come from the first 30% of a page), and
**promotional tone is penalized (~−26%)**. The report explicitly demotes schema
to "machine-legibility hygiene, **not** a citation lever." EverPresent's current
fingerprint over-weights the weak signals (schema/FAQ) and misses the strong
ones.

**Current state.** `engine/audit/presence.py::extract_features` returns
`json_ld, faq_schema, has_tables, recent_year_mentions, word_count`. The
citability diff (`api/dashboards_service.py::_citability_diff`) and briefs
compare only those. Frontend types in `app/src/lib/api.ts`
(`page_features`, ActionPlan `citability.spec`).

**Change.**
- Extend `extract_features` with evidence-based, cheaply-detectable signals:
  `quotation_count` (blockquotes / quotation-mark density around attributed
  text), `statistic_count` (numerals with %/units/currency — a data-density
  proxy), `data_point_density` (stats ÷ word_count), `has_answer_capsule`
  (a 40–60 word paragraph immediately following a question-form heading),
  `front_loaded` (core answer within first 30% of body text),
  `citation_count` (outbound links to authoritative/non-self domains),
  `promotional_tone_score` (marketing-phrase lexicon hit rate — higher = worse).
- Reframe the diff/brief output: present quotations/statistics/capsule/
  front-loading as the primary "do this" levers; keep schema/FAQ as "hygiene."
  Update `_citability_diff` gap strings accordingly and the brief guidance.
- This is a `PagePresence.features` shape change — write a migration only if the
  column is typed/constrained; it is JSON, so likely no migration, but re-crawl
  is needed for new fields to populate (note in the item).
- Frontend: extend `page_features` / `citability.spec` types and the Action
  Plan + Citations rendering to show the new levers.

**Tests.** `tests/test_page_presence.py` + `tests/test_action_plan.py`: a page
with quotes+stats+capsule scores high; a thin promotional page scores low and
yields the right gap lines.

**Acceptance.** Fingerprint returns the new fields; citability diff ranks
Tier-1 levers first; briefs advise quotations/stats/capsules; schema demoted to
hygiene. **Effort:** M–L.

## M1 — Query fan-out (surface + coverage)

**Why.** The report's central strategic claim: engines decompose each prompt
into **9–11 sub-queries** (complex up to 28) and you compete *shard by shard*
(§1.2). EverPresent measures literal prompts only.

**Current state.** `engine/retrievers/gemini_api.py` already parses
`groundingMetadata.webSearchQueries` (the actual fan-out the model ran) into a
local `queries` var but **discards it**. OpenAI/Anthropic expose related
consulted-source breadth (see M6). Briefs generate `subtopics`/`outline`
heuristically (`api/dashboards_service.py`).

**Change.**
- **Capture (part A):** persist the fan-out queries where engines expose them.
  Store on the raw envelope and as a derived field (e.g. a `fanout_queries`
  JSON on `Result` or a small `ResultFanout` table). Gemini is the richest
  source; OpenAI `sources` (M6) and any `web_search_call` query text feed it too.
- **Surface:** a per-prompt "fan-out" view — the sub-queries the engines
  actually issued for this prompt, deduped across engines. New read in
  `api/dashboards_service.py`; expose via a tenant route; render on the Queries
  or a new panel.
- **Coverage (part B):** for each priority prompt, map which sub-questions the
  brand/competitors win (join fan-out queries × which results mention whom).
  Elevate the briefs' `subtopics` from heuristic to evidence-based where
  captured fan-out exists; fall back to heuristic otherwise.

**Tests.** New `tests/test_fanout.py`: a gemini envelope with
`webSearchQueries` → captured + surfaced; coverage view attributes shards.

**Acceptance.** Fan-out queries captured from Gemini (min.) and displayed
per prompt; briefs use real fan-out when present. **Effort:** L.

## M6 — Full consulted-source capture

**Why.** EverPresent captures only *visible* citations; each provider exposes
more (§1.5): OpenAI `sources` (complete consulted list, longer than shown; plus
`oai-sports/weather/finance` licensed-feed labels), Anthropic `cited_text`
(≤150-char quote of exactly what was cited), Gemini `groundingSupports`
(character-span mappings: which claim → which source). The fuller set enriches
Power Pages, target-sources, and grounds citability in what was actually quoted.

**Current state.** `engine/retrievers/openai_api.py` parses `url_citation`
annotations only (its docstring notes "no top-level `sources`" — re-verify
against the current Responses API; the report says `sources` exists). `claude_
api.py` parses `web_search_tool_result` + counts but not `cited_text`.
`gemini_api.py` parses `groundingChunks` but not `groundingSupports`.

**Change.**
- Per adapter, capture the fuller structures into the raw envelope and derive:
  a `consulted_sources` list (distinct from cited) and, where available,
  `cited_text` snippets and claim→source spans. Consider a `source_role`
  (`cited` vs `consulted`) on `Citation` or a sibling table.
- Feed `consulted_sources` into Power Pages / target-sources (a domain
  consulted-but-not-cited is still competitive intel).
- Use `cited_text` to make the citability diff concrete ("engines quoted this
  sentence from the winner").
- Optional: label `oai-*` licensed feeds (see minor m8).

**Tests.** Extend `tests/test_mode_a_providers.py` with fixtures exercising
`sources`, `cited_text`, `groundingSupports`.

**Acceptance.** Consulted (non-cited) sources captured for ≥OpenAI+Gemini;
`cited_text` stored for Claude; Power Pages counts consulted domains.
**Effort:** M–L.

## M4 — Factual accuracy / error detection  *(needs D2)*

**Why.** §2.5: "one confidently wrong AI answer about pricing or accreditation
at scale is a bigger problem than a missing citation." Highest-stakes for Smith
(accreditation) and Greenshield (coverage terms). EverPresent tracks sentiment,
not correctness.

**Current state.** None. Sentiment lives in `Mention.sentiment`.

**Change.**
- Model a `BrandFact` table (tenant_id, key, value/allowed-values, category).
  Admin CRUD in `api/routes/admin.py` + a small admin panel form.
- A checker (in processing, `api/processing_service.py` or a new
  `engine/processing/accuracy.py`) that scans each answer's text for statements
  about tracked facts and flags contradictions (start rule/lexicon-based:
  numeric/price mismatches, named-entity mismatches for exec/role facts,
  presence of disallowed claims). Store per-result accuracy findings.
- Surface an **accuracy** metric on the KPI scorecard and an "errors engines
  repeat" list on the Action Plan (with the source-correction workflow: fix the
  cited page, wherever it lives).
- Degrade gracefully to "no facts on file" when a tenant has no `BrandFact`s.

**Tests.** `tests/test_accuracy.py`: an answer stating a wrong price/exec vs.
the fact sheet → flagged; correct answer → clean; empty fact sheet → skipped.

**Acceptance.** Per-tenant facts editable; wrong answers flagged; accuracy on
the scorecard. **Effort:** L.

## M2 — Natural search-routing measurement  *(needs D1)*

**Why.** §1.3: routing is a hard binary; ~31% of prompts answered from weights
with zero retrieval. EverPresent *forces* search, so it measures the answer
economy but not whether buyers' prompts trigger search at all — "step one" of
any program.

**Current state.** `ResultVariant` = `search` (forced `tool_choice`) /
`nosearch` (no tool). `worker/jobs.py` dispatch + `A_ADAPTERS`.

**Change (per D1; default = sampled probe).**
- Add `ResultVariant.natural` (tool *offered*, not forced) — migration M13 adds
  the enum value (autocommit block; SQLite no-op).
- Adapters: a mode that attaches the search tool without forcing it; capture
  from structured metadata (M6) whether search *actually ran* (`web_search_call`
  present / `groundingMetadata` present).
- Dispatch: run `natural` for a configurable sample of queries (e.g.
  `natural_probe_fraction` in `api/config.py`) to bound cost; exclude from
  answer scoring (like nosearch).
- Surface a per-query **"triggers live search?"** signal and a corpus-level
  "% of your priority prompts that trigger search per engine" — the routing map
  the report says to build first. Reconcile with the existing
  `QueryClassification.web_search_likelihood` (which is an *estimate*; this is
  *observed*).

**Tests.** `tests/test_routing.py`: a `natural` result whose metadata shows a
search call → "searched"; one without → "from weights"; sampled fraction
respected.

**Acceptance.** Observed routing captured for the sampled set; corpus routing
map rendered; cost bounded by the configured fraction. **Effort:** M–L.

---

# MINOR items

Each is small; batch where they touch the same file.

- **m1 — Downgrade llms.txt.** `engine/audit/access.py`: the report finds *zero*
  crawler consumption of llms.txt. Stop penalizing the grade for its absence;
  reframe the issue string as optional/unproven. Update
  `tests/test_access_audit.py`.
- **m2 — Crawler taxonomy 2→3 classes + roster.** `engine/audit/access.py`
  `AI_AGENTS`: split `retrieval` into `search_index` vs `user_fetch`; label
  user-fetch agents (ChatGPT-User, Claude-User, Perplexity-User) as the
  "AI-impression proxy." Add Meta-ExternalAgent / Meta-WebIndexer, Bytespider.
  Encode the insight: blocking OAI-SearchBot removes ChatGPT-search presence;
  blocking GPTBot has no measured Google effect.
- **m3 — Mention-vs-citation divergence.** `api/dashboards_service.py`
  (engine_scorecard / kpi_scorecard): surface, per engine, the gap between
  *mention rate* and *citation rate* (they move independently; Gemini overlap
  can hit 30%). Frontend chip on the scorecard.
- **m4 — Per-engine source-type patterns.** Enrich citation `source_category`
  (`engine/processing/citations.py`) with type buckets (encyclopedia/publisher,
  community/Reddit, video/YouTube, review/G2) and tailor the third-party
  playbook per engine (ChatGPT→Wikipedia/publishers, Perplexity→Reddit,
  AIO→organic-index/Reddit/LinkedIn).
- **m5 — Entity-authority checks.** Access/entity audit: detect `sameAs`
  schema, Wikidata/Wikipedia presence, and consistent naming (Pillar C).
- **m6 — Engine coverage gaps.** Optional new surfaces: Copilot (Bing), Meta AI,
  Grok — follow the `A_ADAPTERS` / `B_ADAPTERS` registry pattern in
  `worker/jobs.py` (one entry + adapter + cost fn each). Only 36 brands hold
  cross-surface visibility; coverage is a selling point.
- **m7 — Model-release re-baseline flag.** The diagnosis-twin cache already
  invalidates on model change (`worker/jobs.py` envelope-model check); surface
  an explicit "priors re-shuffled → re-baseline recommended" notice when the
  configured model for a surface changes.
- **m8 — Licensed-feed (Layer 3) labels.** Once M6 lands, detect and label
  `oai-sports/weather/finance` in OpenAI output so licensed-feed answers are
  distinguished from open-web retrieval. Niche.

---

## Cross-cutting acceptance

- After each item: `pytest` green, `ruff` clean, `tsc` clean; new migration (if
  any) has verified offline SQL and a downgrade.
- No banned model substrings in scanned paths; no model id in commits/PRs.
- Every new metric/verdict ships with its one-line "why / do this" copy — the
  product's value is the recommendation, not the raw number.
- Prefer extending existing panels over new tabs; match the light/dark token
  system in `app/src/app/globals.css`.

## Out of scope (flagged, not planned here)

- **Server-log AI-crawler ingestion** and **GSC integration** (great-decoupling
  ratio, blended-SERP CTR, branded-search lift). High value but require client
  log/GSC access — treat as a separate initiative with its own data-access
  design.
