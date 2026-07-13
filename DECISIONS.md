# Decisions of record

Spec §11.7: when the spec is ambiguous, choose the smaller interpretation and
note it here.

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
