# EverPresent — Demo Readiness Checklist

Everything that has to be true for a live GoDaddy demo, in the order you'd do
it. `[ ]` items are yours to confirm. Env var names map to `.env.example`.

---

## A. Provision accounts & secrets

The four measurement keys + the proxy are the demo-critical ones; the rest boot
the app or enable optional features. Full list and notes in `.env.example`.

- [ ] **OpenAI** API key → `OPENAI_API_KEY` — ChatGPT (API)
- [ ] **Anthropic** API key → `ANTHROPIC_API_KEY` — Claude (API) **and** steps 4 & 5 (the one key does both)
- [ ] **Google Gemini** API key → `GEMINI_API_KEY`
- [ ] **Perplexity** API key → `PERPLEXITY_API_KEY`
- [ ] **Residential proxy / scraping browser** (Bright Data or similar) → `SCRAPE_PROXY_URL` (or `SCRAPE_PROXY_MAP` / `SCRAPE_CDP_ENDPOINT`).
      Powers **Copilot + ChatGPT-web + Perplexity-web + the power-page crawler**. Without it those come back `blocked` from a datacenter IP.
- [ ] **Clerk** keys (3) → `CLERK_*` (+ `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` on the web service), and `SUPERADMIN_EMAIL`
- [ ] **Postgres** + **Redis** → `DATABASE_URL`, `REDIS_URL` (Render provisions both), `STORAGE_BACKEND=db`
- [ ] *(optional)* **SerpApi** → `SERPAPI_KEY` + `GOOGLE_AIO_PROVIDER=serpapi` — only if you want Google AI Overviews as a 6th surface
- [ ] *(optional)* **SMTP** → run-completion emails · **GCP service account** → BigQuery mirror + GA4 outcome (skip GA4 for the demo — you won't have GoDaddy's property)

## B. Deploy & migrate

- [ ] Deploy branch `claude/everpresent-v3-rebuild-wy4ybi`
- [ ] Run migrations: `alembic upgrade head` → head is **`e7f8a9b0c1d2` (M23)**. Without this the `copilot_web` enum value and the steps-4/5 tables don't exist.
- [ ] Seed: `python -m api.seed` → creates the **GoDaddy tenant** from `seeds/godaddy.yaml` (idempotent; skips if it already exists)
- [ ] Confirm three services are up: **api** (web), **web** (Next.js), **worker** (Playwright image, runs `worker.combined` = both queues + the scheduler)

## C. Per-tenant admin config (GoDaddy)

The YAML seed sets brand/competitors/personas/queries/surfaces + the Q3 fact.
These are the governance/plan toggles the seed deliberately does **not** set —
do them in the admin panel:

- [ ] **Plan = Command or Custom** (uncapped engines). Lower plans cap engines (Monitor 3 / Diagnose 4) and will drop surfaces — you have 7.
- [ ] **`approved_surfaces`** includes all seven, **including `copilot_web`** (a run only dispatches surfaces that are enabled **and** approved **and** within the engine cap)
- [ ] **`ai_processing_approved` = true** (required for runs, and for steps 4 & 5)
- [ ] **`entity_extraction_enabled` = true** + **`approved_utility_models`** = `["claude-haiku-4-5-20251001","claude-sonnet-4-6"]` (lights up the Whitespace slide and the corrective-content button)
- [ ] **`monthly_spend_cap_usd`** set high enough for a full daily matrix across 7 surfaces (the cap is enforced pre-dispatch — too low and calls get withheld)
- [ ] **Verify the Q3 fact** (`seeds/godaddy.yaml` → `brand_facts`). It's a **placeholder** — confirm GoDaddy's real domain-privacy policy before relying on the accuracy demo.
- [ ] *(optional)* **Locations** for the location fan-out (needs `SCRAPE_PROXY_MAP`); **`notify_emails`** for run reports
- [ ] **Set the daily collection schedule**: `PUT /api/admin/tenants/godaddy/schedule` with a `cron_expr` (e.g. `0 7 * * *`). Collection can't be backfilled — start it as early as possible.

## D. Subsystem readiness

| Subsystem | Needs | Verify |
|---|---|---|
| **Mode A** (ChatGPT/Claude/Gemini/Perplexity API) | the 4 keys | trigger a run; results are `ok` with citations |
| **Mode B** (Copilot, ChatGPT-web, Perplexity-web) | Playwright worker + **proxy** | run the Copilot smoke test (§E); results `ok` not `blocked` |
| **Google AIO** *(optional)* | `SERPAPI_KEY` + provider=serpapi | AIO tile populated on Overview |
| **Steps 4 & 5** (Whitespace + content-gen) | `ANTHROPIC_API_KEY` + governance flags (§C) | Whitespace page lists untracked names; "Generate corrective content" returns a draft |
| **Power-page crawling** | citations to exist + **proxy** (now routed through `SCRAPE_PROXY_URL`) | after a run, trigger a crawl; pages come back `ok`, not all `error/403` |
| **Nightly jobs** | scheduler running (`worker.combined`) | fire after `MIRROR_HOUR_UTC`: power-page crawl runs for any tenant with citations (auto); mirror/GA4 only if configured |
| **Emails** *(optional)* | `SMTP_*` | run-completion email arrives |

## E. Pre-demo smoke tests

- [ ] **Backend green** (dev box): `python -m pytest -q` · `ruff check api/ worker/ engine/ tests/` · `cd app && npx tsc --noEmit`
- [ ] **Copilot selectors** (the one thing I couldn't validate for you): from the worker or a machine with real egress —
      ```
      python scripts/smoke_copilot.py --query "What's the best AI website builder?"
      ```
      Exit `0` = good (prints citations + a Reddit/YouTube yes-no). `3` = blocked → proxy. `4/5` = selectors need updating (screenshots show the live DOM; edit `copilot_web_selectors.py`).
- [ ] **One real run**, then on the run detail confirm: each surface present, `web_search_calls > 0` on the search variant, and **Reddit/YouTube appear in citations on the web/Copilot/Perplexity surfaces** (they won't dominate the API surfaces — that's expected).
- [ ] **Power-page crawl** produces `ok` rows (not all 403) — proves the proxy is wired for the crawler too.
- [ ] **Closed loop**: on the Scorecard accuracy card, click **Generate corrective content** for Q3 → a draft renders. This is the demo's money shot.

## F. Known caveats — go in with eyes open

1. **Q3 fact is a placeholder** — verify GoDaddy's real domain-privacy policy or the accuracy demo undercuts itself.
2. **Copilot selectors are best-effort** against a volatile DOM — the smoke test is the gate; keep the one-file fix (`copilot_web_selectors.py`) handy.
3. **The proxy is load-bearing** — Copilot, the two web surfaces, and the Reddit/YouTube-source story all depend on it. API keys alone give you four surfaces, not the differentiated ones.
4. **GA4/Outcome** needs GoDaddy's GA4 property access you won't have for a demo — leave it off; every other screen stands on its own.
