# Decisions of record

Spec §11.7: when the spec is ambiguous, choose the smaller interpretation and
note it here.

## M35 — Weekly briefing and leaner navigation (2026-10-04)

1. **Briefing on the Overview.** Three answers on one screen: are we winning
   (mention rate, range, real-change test, top rival by share of voice), why
   (top alerts, a model switch, memory-vs-search gaps, the top objection) and
   this week (the top three open plays, strategy excluded). It only composes
   existing reads, so it can't disagree with the pages it summarises. When
   the change test lacks data, it says so instead of claiming "no change".
2. **Navigation.** Three groups for the weekly loop (Overview, Visibility,
   Act). Brand, Personas, Fan-out, Whitespace, Action Plan and Runs move into
   a collapsed "More" group that opens when one of them is the current page.
   No page was removed, and no URL changed.

## M34 — Demo-proofing: engine check, honest copy, sample-size planner (2026-10-04)

1. **Engine smoke test.** Admin "Test every engine" makes one short live call
   per enabled engine through the real adapters (cents, recorded in the spend
   ledger) and checks the parts dashboards depend on: answer text, sources or
   searches, served model. The newest check feeds the readiness table, so a
   bad key, a missing browser or a changed response format shows before a run.
   Common failures are explained in plain words.
2. **No unverified figures in product copy.** Industry numbers circulate
   second-hand; the playbook, briefs and page intros now name the kind of
   evidence (official guidance, controlled study, vendor tracking) instead of
   quoting figures we couldn't check against the original source.
3. **Sample-size planner.** The headline change test compares the halves of a
   fixed 28-day window, so waiting longer doesn't help a thin engine; the
   answers per two weeks must grow. Per engine: answers per half-window, the
   answers a 10-point change needs (two-sided 5%, 80% power), the smallest
   change detectable now, and how many times more data is needed.

## M33 — Answer shape, memory vs search, your pages, first-party data (2026-10-04)

Driven by the October research ("Future proofing AEO beyond citations"):
newer ChatGPT models search less and cite fewer third-party sites, but still
cite, mostly the brand's own pages, with inline brand links since May 2026.
Citation counts are the wrong scoreboard, so:

1. **Every answer records its shape.** The served model (from the API
   response), signed-in state for web captures, and per-citation link kind
   (inline brand link vs source chip; inline = brand name linking the
   homepage). Observed model switches become series notes and a playbook card.
2. **Memory vs search is a headline split**, from the existing no-search twin
   plus unforced probes, with 95% ranges. Themes/objections come from stored
   mention sentences that name the brand (deterministic lexicon, no LLM spend).
3. **Your Pages** audits the brand's own cited pages: crawl status, update
   date, fact-sheet conflicts (crawler checks visible text), AI bot reads.
   A 403 to our checker while AI bots read the page is "blocks our checker",
   not "unreachable".
4. **First-party data is imported as CSV** (Search Console, Bing, Merchant
   Center, Cloudflare, GA4) with name-based column mapping; re-imports replace
   cells. Only Cloudflare/GA4 have usable APIs today; connectors can follow.

## M32 — October sweep hardening (2026-10-03)

1. **Log input is hostile by default.** Anyone can make a request to a
   tenant's site with a bot user agent, so every parsed field is bounded:
   control characters are stripped from paths, statuses outside 100–599
   become 0, bad timestamps are skipped, lines over 16 KB are dropped
   without being buffered, and every regex is bounded and non-overlapping.
2. **Uploads stream in linear time and bounded memory**, with parsing and
   database work in a worker thread so one upload can't stall the API.
   Cells are written with INSERT … ON CONFLICT DO UPDATE, so concurrent
   pushes add up exactly. Uploads still add (that's how log drains work);
   the response lists days that already had data so a re-upload is visible.
3. **Push tokens are stored as SHA-256 digests** (m32 hashes existing ones).
4. **Crawler feature checks read only visible text** (no scripts/styles) and
   every pattern is bounded; the worst hostile page went from minutes to ~1 s.
5. **Playbook stability.** Each play source runs in a savepoint; a source
   that fails, or has only stale data, leaves its existing plays untouched.
   Lost-citation plays stay open until the page is cited again. One play
   per wrong fact. Only refusals (401/403/429/5xx) count as a bot blocked.
6. **(tenant_id, gap_ref) is unique** on recommendations.

## M30–M31 — Agent Analytics and the evidence-graded playbook (2026-10-03)

1. **Recommendations follow the 2026 evidence order.** Controlled studies
   (252k-trial factorial test; CITECHOICE causal replay) show retrieval
   (sub-query coverage) and explicit facts (prices, dates, ratings) change
   whether a page is cited; formatting only shifts credit among retrieved
   pages. Briefs, the citability diff and the playbook rank plays that way,
   and every play carries an evidence grade (official / strong / moderate /
   emerging) and a one-line source statement.
2. **A query is a gap when the brand is named on fewer than a third of the
   engines**, not only when it is named on none: missing on 8 of 9 engines is
   not a win. Text names the engines on each side.
3. **Similar plays are grouped** (one per query for sub-questions, one for
   dead pages, one for read-not-cited pages) so the list stays workable.
4. **Engine-specific advice.** ChatGPT's August 2026 shift to in-site
   searches (Reddit citations down ~86%) makes help/docs/pricing pages the
   ChatGPT play; community plays are scoped to Google and Perplexity.
5. **A failing signal never blocks the rest.** Each play source is isolated
   and logged on failure; run processing never fails on recommendations.
6. **Lost-citation diffs use normalized brand URLs** and skip redirect
   wrappers (Gemini grounding links), which can't be refreshed as pages.

## M26–M29 — measurement credibility (2026-10-01)

Driven by the Sept 2026 AEO research (repeated-sampling studies, API-vs-UI
divergence, Perplexity's API change, Google's spam policy).

1. **Mention rate is the headline, with a 95% Wilson range.** Pooled over the
   window (default 28 days) from every ok search answer to a competitive query,
   per engine and overall. A change is called only when the window's two halves
   differ at p < 0.05 with 30+ answers a side. Answer Share and average position
   stay, labelled "directional": brand order rarely repeats run to run.
2. **Repeated sampling on generic cells only** (Monitor 1, Diagnose 2,
   Command/Custom 3 samples per run), rotating through `queries.paraphrases`.
   Results keep the canonical `query_text`; the envelope records the wording
   asked. Persona cells and Mode B stay at 1 (cost). Recommended cadence is
   3×/week rather than daily: more samples per dollar.
3. **Perplexity on the Agent API** (`/v1/agent`, `perplexity/sonar`, forced
   web_search) since Sonar chat completions retired on 2026-09-27. Presets are
   avoided because they resolve to OpenAI models; `sonar-pro` has no Agent slug.
   One fallback to the legacy endpoint on a 400/404/405/422, tagged in the
   payload. The Overview flags trends that span the switch.
4. **Google AI Mode via SerpApi** (`engine=google_ai_mode`), per query and
   location like AI Overviews. Empty captures are errors, never "absent".
   Kept behind the provider module because Google v. SerpApi is unresolved.
5. **Contestability = churn in the set of brands named**, not answer-text
   churn (text changes nearly every run, so the old measure called everything
   volatile).
6. **Spam-policy guard on content advice.** Briefs for "best/top/vs/
   alternatives" queries carry a warning and point to earned third-party
   placement; the drafting prompt refuses self-ranked lists.
7. **Gemini on 3.x** (economy 3.5 Flash-Lite, standard 3.6 Flash, premium
   3.1 Pro preview). 2.5 Pro is deprecated for 2026-10-16 and already refuses
   new users; Gemini 4 "Argon" (announced 2026-09-30) is limited-access only.
   Gemini 3 takes `thinkingLevel: low` (never with thinkingBudget). A retired
   or unavailable model falls back once to `gemini-3.6-flash`, tagged in the
   payload. Prices are third-party figures, the higher list price used.

## M25c — fan-out close the loop (2026-09-30)

1. **Brief only for a measured miss.** The service refuses any shard that
   wasn't re-probed or where the brand was present — no brief is ever built on
   an unresolved guess. The button shows on HIGH rows (the spec's worklist);
   the service would also accept a MED miss if a caller asks.
2. **Same governance as the accuracy drafts:** ai_processing_approved + the
   draft model on the tenant allowlist + a key, else 409 with the reason. The
   shared call-and-upsert step moved into one helper (`content_service._draft`).
3. **Context comes from the re-probe answer itself**: the winners, how the
   answer framed them (mention-detector snippets) and the domains it cited.
   The prompt asks for [placeholders] instead of invented facts or prices.
4. **One draft per shard text, not per row** (`source_ref = shard:<shard_norm>`,
   `source_kind = fanout`): the same shard recurs every run under a new row
   id, and regenerating replaces rather than piles up.
5. **Trend = latest distinct re-probe vs the one before it.** Only original
   measurements (`probe_status=ok`) are data points; carried copies aren't, so
   a shard can't "trend" against itself. With the 7-day TTL a shard gets a new
   data point about weekly. A first measurement has no trend (null).

## M25b — fan-out re-probe (2026-09-30)

1. **K settled from a cost model, lower than the spec's 5 / 12.** Per-probe
   estimates from `engine/costs.py` at each plan's model tier: an OpenAI probe
   is ~$0.02 (economy) to ~$0.07 (premium); a Gemini probe is ~$0.14 at every
   tier, because grounding bills $35/1k *per sub-query* and a probe fans out
   again (~4 queries). Most shards are Gemini-issued, so the blended cost is
   ~$0.11–0.13/probe. Target: re-probe spend ≈10% of the plan price at one run
   a day.
   | Plan | K / prompt | Ceiling / run | ~Max probes / mo | ~Max spend / mo |
   |---|---|---|---|---|
   | Monitor ($149) | 0 (map only) | 0 | 0 | $0 |
   | Diagnose ($549) | 2 | 15 | 450 | ~$50 |
   | Command ($2,900) | 5 | 75 | 2,250 | ~$290 |
   | Custom | 5 | 75 | — | spend cap governs |
   Everything still runs through `monthly_spend_cap_usd` (default $50), so a
   Diagnose tenant needs its cap raised to use the full re-probe allowance.
2. **7-day freshness TTL** (`FANOUT_REPROBE_TTL_DAYS`). A shard re-probed within
   the TTL carries its presence forward (`probe_status=carried`) instead of
   being re-bought, so the per-run ceiling rotates coverage across the whole
   shard set week to week. Same idea as the diagnosis-twin cache.
3. **Probe on the cheapest engine that issued the shard** (OpenAI before
   Gemini), never on an engine that didn't issue it — presence is measured
   where the contest happened. One probe per shard, baseline persona.
4. **Winner attribution reuses the mention detector** (spec open question 2):
   present = the answer names you or cites an owned domain; a competitor "won"
   the shard on the same test.
5. **Shard probes write a `Result(variant="shard")` but NO Mention/Citation
   rows.** Presence lives on `FanoutShard`, so no mention or citation read —
   even one that filters only by tenant — can count a probe. Tighter than the
   spec's "run through the existing extraction", same classifier.
6. **HIGH no longer requires reach ≥ 2.** Only Gemini and OpenAI expose
   fan-out, and an exact shard match across both is rare, so the spec's gate
   would leave HIGH near-empty. HIGH = absent + a competitor won; MED = absent,
   no tracked winner; LOW = present. Reach orders shards within a band.
   Unresolved shards get no priority at all — no claim without a measurement.
7. **No "grounded" source.** §2 established that no engine maps sources to a
   shard, so the only honest sources are `reprobed` and `unresolved`.
8. **Re-probe is its own RQ job** (`worker.jobs.run_fanout_reprobe`), enqueued
   by `_finalize_run` once the run is final: no nested event loop, no DB
   connection held during provider calls, and a probe failure never touches
   the run's status. Drops are stamped per shard (`dropped_k`,
   `dropped_ceiling`, `withheld_cap`, `error`) and counted on the run.
9. **Deferred:** audience-weighted composite (spec open question 3) — its own
   small milestone; M25c (corrective brief per HIGH miss, trend deltas).

## M6 (2026-07-13)

1. **AIO CLASSIFIER IS UNCALIBRATED — §12.1 remains open.** The rule-based
   classifier ships as `v3.0.0-uncalibrated` with provisional thresholds
   (top-of-page + expanded/≥1200 chars → aio_dominant; top → aio_plus_organic;
   below organic → organic_dominant). Neil's 40 labeled seed queries have not
   been provided. `tests/test_aio_calibration.py` activates automatically the
   moment `seeds/aio_labels.yaml` exists (format:
   `seeds/aio_labels.example.yaml`; target ≥80% agreement). After calibrating,
   drop the `-uncalibrated` suffix and reprocess via the admin endpoint.
2. **AIO capture is per (query, geo), no persona** — a SERP takes no system
   prompt. Result rows use persona_name "(serp)"; per-tenant geolocation
   lives in `tenants.aio_geo` (gl/hl, optional lat/lng), defaulting to
   Canada/English.
3. **SerpAPI fallback is built, not just designed** (§6.3 names it): set
   `GOOGLE_AIO_PROVIDER=serpapi` + `SERPAPI_KEY` if direct capture proves
   non-viable from the VPS IP — the likeliest of all surfaces to be blocked.
   Both providers produce the same outcome shape and classifier input.
4. **AIO fields upsert onto the query's existing classification row(s)**
   (§5.1 keeps one classifications table); queries measured only by AIO get
   a row keyed to the google_aio surface with an empty web bucket. The AIO
   dimension never collapses into web-search-likelihood (§5.2).
5. **Recommendation matrix (§6.4):** gaps are active queries whose latest
   answers never mention the brand; branch by classification (very_likely/
   likely → web_search; unlikely → training; "possible" gets no prescription).
   The AIO branch triggers independently when the Overview is dominant/
   present and cites none of the brand's domains. `branch` is an extra column
   beyond the spec's four. Regeneration is idempotent: human done/dismissed
   survive, closed gaps auto-resolve, reopened gaps come back.

## M5 (2026-07-13)

1. **Schedules store cron only.** §5.1 lists surface_set/mode_set on
   run_schedules; the smaller interpretation resolves surfaces and modes from
   the tenant's live config + governance at fire time, so a schedule can
   never dispatch something the admin panel says is off. One schedule per
   tenant.
2. **Scheduler is a tiny loop service,** not rq-scheduler: a 30-second tick
   over `run_schedules` (croniter), firing through the same `trigger_run`
   service the admin button uses. New/re-enabled schedules arm without firing
   retroactively. The nightly BigQuery mirror is enqueued by the same tick
   (first tick past MIRROR_HOUR_UTC each day).
3. **Notifications are SMTP,** provider-agnostic, with the summary PDF and
   per-run results CSV attached. Unset SMTP host = skipped, never crashed;
   notification failure never fails a run. The §9 80%-cap alert rides the
   completion email as a SPEND ALERT block (plus the existing admin-UI
   indicator).
4. **BigQuery mirror without the Google SDK:** service-account JWT grant via
   PyJWT + the REST API (create-if-missing v3-suffixed tables, insertAll with
   insertIds). Metadata only — raw_uri and payloads never enter the
   warehouse. Watermarks in `mirror_state` make it idempotent; streaming
   inserts + insertIds make retries safe. Nothing client-facing reads
   BigQuery.
5. **Perplexity adapter reuses the shared extractor** (stdlib HTML→text+links
   moved to `engine/retrievers/html_extract.py`); adapters differ only in
   selectors files and skip-host lists. Mode B dispatch is a per-surface
   registry with per-surface rate limits.

## M4 (2026-07-13)

1. **Mode B volume: one cell per (query, surface) on the first persona.**
   §6.2's fresh-session pattern is "per query"; the full query×persona matrix
   through a browser at 4/min would take hours per run. The smaller
   interpretation keeps scrape volume at corpus size — the fidelity
   comparison per query, which is what the Queries screen shows. Widening to
   the full matrix is a one-line change in `_run_mode_b` if wanted.
2. **Persona framing + query as ONE opening message.** "Pastes the framing
   as the opening message, submits the query" could read as two turns; one
   combined message halves latency and avoids the model replying to the
   framing itself. `build_opening_message` is the single place to change.
3. **A chains into B; the last job finalizes.** One run row spans both modes.
   Rather than coordinate two workers racing on the same row, the Mode A job
   enqueues Mode B when web surfaces are eligible and only the final job sets
   the terminal status and runs processing. A hard A-failure (missing
   OPENAI_API_KEY) finalizes as failed without scraping.
4. **Logged-out ChatGPT.** The adapter drives chatgpt.com without an account
   (dismissing the stay-logged-out interstitials): cleanest fit for the
   no-memory rule and no credential store needed yet (§9's separate
   credential store comes when a surface requires login). Datacenter-IP
   blocking is an operational risk; failures land as error-status results,
   and selectors live in `chatgpt_web_selectors.py` for five-minute fixes.
5. **No nosearch twin and no spend cap for Mode B.** A consumer UI can't
   disable retrieval, so classification stays an API-surface concern; B costs
   no tokens and is rate-limited (default 4/min) instead of cap-checked.

## M3 (2026-07-12)

1. **v3-NATIVE PROCESSING, NOT A v1 PORT — owner-directed exception to
   §11.4.** The spec requires porting the Query Intelligence classifier,
   mention detection, and visibility scoring verbatim from v1 with their
   regression sets. No v1 source exists in this session's repos (re-verified
   before M3 started: Everpresent had only v3 work; gtdt contains an
   unrelated GTD-app spec). The blocker was raised at the M0, M2 gates; Neil
   directed "Build M3" with that knowledge, which is read as authorization to
   implement fresh. Consequences:
   - `engine/processing/` (mentions, classify, scoring, citations) is new
     code, versioned `v3.0.0`, with `tests/test_mentions.py`,
     `test_classify.py`, `test_scoring.py` as the NEW golden regression set.
   - If the v1 source surfaces: port it, run both regression sets, bump the
     version strings, and reprocess history via
     `POST /api/admin/runs/{id}/process` (processing is idempotent by
     design for exactly this).
2. **Classifier buckets.** `very_likely / likely / possible / unlikely`, from
   three signals: web_search tool calls, citation count, and token-level
   divergence between the search-enabled and search-disabled answers
   (threshold 0.45). One nosearch twin per (query, surface) per run, on the
   first persona — cost is +1 call per query, not ×2 the whole matrix.
3. **Scoring formula.** score = 100·(0.60·mention_rate + 0.25·mean(1/rank) +
   0.15·own-domain citation rate) per (surface, segment, day); competitors
   scored symmetrically. Share of voice = entity mention counts over 30 days.
4. **Sentiment is a window lexicon,** not an LLM call — deliberately, to keep
   M3 rule-based and CI-deterministic. Upgrading to Haiku via the §4 router
   is the designed next step once a tenant approves utility models; the §4
   router itself ships when its first real caller does.
5. **Rollups recompute whole days** (all runs of that tenant-day), so
   repeated same-day runs never double-count, and `visibility_daily` stays
   append-free/idempotent.

## M2 (2026-07-12)

1. **Results snapshot config by value.** YAML re-import replaces persona and
   query rows wholesale (M1.3), so `results` stores `query_text`,
   `persona_name`, and `persona_segment` copies; `query_id`/`persona_id`
   remain as unconstrained integers for convenience, not FKs.
2. **Cost figures are estimates.** `engine/costs.py` holds a static price
   table (documented as estimates for cap enforcement and reporting, not
   billing truth). The pre-dispatch cap check can overshoot by at most the
   concurrency limit's worth of in-flight calls, since a call's actual cost
   is only known after it returns.
3. **Spend-cap alert at 80% is a UI indicator for now** (admin runs page);
   push notifications belong to M5's notifications work.
4. **Search-disabled dual-query variant is built but not dispatched.** The
   retriever supports `web_search=False` (`build_request_body`); the run
   matrix dispatches only the search-enabled call until the M3 classifier
   consumes the diff, keeping M2 spend at one call per cell.
5. **Raw envelopes, not bare payloads.** Object storage holds a JSON envelope
   (request context + full provider response + parsed text) at a
   `RAW_STORAGE_DIR`-relative URI, so the volume can move without rewriting
   rows and the raw viewer needs no re-parsing.
6. **`citations.source_category` stays empty until M3** processing lands its
   rule-based categorization against tenant brand/competitor domains.

## M1 (2026-07-12)

1. **One branch, not branch-per-milestone.** §11.1 says a branch per
   milestone; this session's operating constraints designate a single branch
   (`claude/everpresent-v3-rebuild-wy4ybi`) and forbid pushing elsewhere. All
   milestones land there sequentially, gates still apply.
2. **Alembic from M1.** Schema is now migration-managed (`alembic upgrade
   head` runs in the deploy script before the stack comes up). The app never
   `create_all`s in prod; tests still build their in-memory sqlite schema
   directly. If an M0-era deploy ever ran `create_all` on a real database,
   drop that database before the first M1 deploy — there was no data.
3. **Seed YAMLs are placeholders.** The real v1 Smith/Greenshield YAML
   configs are not in this session (same gap as DECISIONS M0.2). `seeds/*.yaml`
   carry clearly-marked starter corpora so the M1 gate is demonstrable; the
   importer is replace-semantics, so re-importing the real files from the
   admin panel swaps them wholesale. Greenshield's `early_retirees` persona
   segment is included per §7.1.
4. **Seed never clobbers.** `api.seed` imports a tenant's YAML only when
   creating that tenant; existing tenants are left untouched on every
   subsequent deploy. Config changes after that go through the admin panel.
5. **Clerk org linking is manual.** The admin page takes a pasted `org_…` id
   rather than creating orgs via the Clerk API — smaller interpretation, and
   org creation/invites stay in Clerk's dashboard where invite flows already
   work. Membership rows mirror the org claim lazily on first request.
6. **Governance validation at the API layer.** `approved_utility_models` must
   be a subset of `RUNTIME_LLM_ALLOWLIST`; the policy guard test also scans
   `api/**` — it caught a code comment naming the forbidden tier during
   development, which is exactly the intended behavior.

## M0 (2026-07-12)

1. **Repo naming.** The spec calls the repo `everpresent-v3`; the GitHub repo
   this session is scoped to is `neilbearse-droid/Everpresent` (empty at
   start). The monorepo lives there — contents match the spec layout
   (`app/`, `api/`, `engine/`, `infra/`, plus `worker/` split out for the RQ
   entrypoints).
2. **No v1 code in reach.** The spec says to port the Query Intelligence
   classifier, mention detection, and scoring verbatim from v1 with their
   regression sets, but no v1 codebase exists in this session's repos
   (`Everpresent` had zero commits; `gtdt` is a stub). **Blocker for M3, not
   M0–M2:** Neil needs to add the v1 source (or its repo) before M3 starts.
   Per §11.4 this will not be silently reimplemented.
3. **Superadmin lives on `users.is_superadmin`.** §5.1 lists `superadmin` as a
   membership role, but memberships are per-tenant and the superadmin is
   cross-tenant. A boolean on the user row is the smaller interpretation;
   membership roles stay `owner|member`.
4. **Seed-then-link auth.** The seed creates the superadmin user by email
   (`SUPERADMIN_EMAIL`); the Clerk user id is linked on first authenticated
   request (email fetched once from the Clerk backend API, since default
   session tokens don't carry email and custom JWT templates would couple us
   to Clerk config).
5. **`create_all` now, migrations at M1.** No data exists at M0, so schema
   creation is `SQLModel.metadata.create_all`. Alembic lands with M1 when the
   tenancy schema starts carrying real config.
6. **M0 e2e scope.** Playwright covers the public landing page and the
   anonymous→sign-in redirect with placeholder Clerk keys. Signed-in flows
   join at M1 with real test-instance keys.
7. **Clerk placeholder keys in CI are `pk_live_`-style.** Dev-instance keys
   (`pk_test_`) trigger Clerk's dev-browser handshake redirect for anonymous
   visitors, which breaks e2e against a key that points at a nonexistent
   Clerk instance. Production-style placeholders skip the handshake; no Clerk
   network traffic happens in CI either way.
