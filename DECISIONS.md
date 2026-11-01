# Decisions of record

Spec §11.7: when the spec is ambiguous, choose the smaller interpretation and
note it here.

## M58 — Answers are saved as they return; a failed run can be resumed (2026-11-01)

1. **Why.** Run #52 died when a deploy restarted the worker: Mode A saved
   its answers only after the whole batch came back, so 201 paid-for answers
   and their cost were lost, and the spend cap never saw the money.
2. **Save as you go.** Each Mode A answer is written in its own short
   transaction the moment it returns (`_persist_a_outcome`): Result row,
   citations, consulted sources, raw envelope, and the run's counts and cost
   in the same commit, serialised by a lock. The dispatcher still holds no
   connection across the batch. Phase 3 only adds the cached twins, counts
   citations from the table and sets the status; `run.cost_usd` is never
   overwritten with a total. Envelope names carry a nonce so a resumed run
   can't reuse one. Mode B already saved per capture.
3. **Planners skip what the run holds.** Both modes subtract the ok answers
   a run already has, cell by cell (`_skip_done`), with samples of one
   wording told apart by count. A fresh run has nothing to skip, so this
   costs nothing; a resumed run re-asks only the missing cells, including
   cells that errored.
4. **Resume.** `POST /admin/runs/{id}/resume` puts a failed run back to
   pending and re-queues it (refused while the tenant has a live run);
   counts carry the per-engine cost and a `resumed` count. The admin Runs
   page shows a Resume button on failed runs. A crash in Mode A still marks
   the run failed; Resume is the recovery path, not auto-retry.
5. **Pushes and runs.** A push redeploys the worker and kills a run in
   flight. The rule from here: push only when no run is in flight, and say
   so before pushing.

## M57 — The pooled headline weights engines by audience (2026-11-01)

1. **Audience weights, said out loud.** The overall mention rate, its
   unforced twin and the visibility trend now weight engine families by
   audience share: `Σ weight × rate / Σ weight` over the families the client
   measures (`api/engine_weights.py`). A family with no answers drops out of
   the denominator; weight 0 is measured and shown per engine but not
   pooled. Surfaces of one engine (ChatGPT API and web) pool their answers
   first, so measuring an engine twice doesn't double its vote. Per-engine
   rows, topics, personas and proof are unchanged (proof stays one answer,
   one vote per question).
2. **The default table is a judgement, dated and sourced**: ChatGPT 40,
   Google AI Overviews 20, Gemini 12, Google AI Mode 10, Claude 8, Copilot
   4, Perplexity 3, Meta AI 3. Anchored in Similarweb visits and StatCounter
   referrals (Sept 2026); neither panel covers Google's AI surfaces, so
   those rows are placed by judgement and the admin page says so.
3. **Per-client override** (Admin → Audience weights; `tenants.engine_weights`,
   m39). B2B software leans Claude and Perplexity; consumer brands the other
   way. Every change is dated (`engine_weights_changed_on`) and becomes a
   note on the pooled line only: the trend shows it, the alert bar withholds
   the pooled verdict across it, proof ignores it.
4. **Statistics.** The weighted rate's 95% range comes from the weighted
   variance of the family proportions (Agresti–Coull shrinkage so a 0-of-5
   cell doesn't claim zero noise); the change test is the difference of the
   two weighted rates over the root of their summed variances, with the
   usual 30-answer floor per side. The equal-weight pool is kept in the
   payload (`overall.equal`) and printed beside the headline so the two can
   be compared; the scorecard, Overview and PDF state the weights.
5. **Rates move.** For a client measuring Perplexity or Claude alongside
   ChatGPT, the headline shifts toward ChatGPT's rate the day this lands.

## M56 — Cost by engine on the admin run page (2026-11-01)

1. The worker books each call's estimated cost against its engine in
   `run.counts` (`cost:<surface>`, `reprobe_cost:<surface>` for fan-out
   re-probes) as the run goes, including SerpApi follow-up searches. The
   admin run detail (`with_cost=True`) returns `cost_by_engine`: answers and
   cost per engine with share of the run, the re-probe line split by engine,
   and whatever the counters don't attribute. The client-facing run detail
   never carries it (cost reveals the margin).
2. Runs from before the counters are summed once from the stored answers'
   envelopes and the result written back to `run.counts`
   (`cost_breakdown_source: envelopes`), so later reads cost nothing.
3. Why it was asked: a 680-answer Command run on Oct 8 cost $24.70. Gemini
   3.x bills $14 per 1,000 searches and fans out several searches per answer,
   and the run carried the old 75-probe re-probe ceiling (cut to 15 in M52).

## M55 — Week one of the October 2026 sweep (2026-10-31)

Fixes from the best-practice sweep (reports/AEO best practice sweep October
2026.md): the seven bugs, the series breaks, the engine order and the copy the
evidence contradicted. Headline rates move for existing clients: see 1 and 8.

1. **Branded questions can't leak in through import.** The brand-naming rule
   (`api.yaml_import.names_brand`: name, aliases, domains, whole word) now
   applies on YAML import as it did on the add box; explicit `branded: true`
   is kept and the import result lists what it filed (`auto_branded`). The
   GoDaddy, Smith and GreenShield seeds had leaks (e.g. "GoDaddy vs.
   Namecheap") and are corrected, so GoDaddy's headline falls. Existing
   clients: admin "Re-check branded" (`POST …/queries/recheck-branded`) flips
   stored rows and lists them; live reads re-scope at once, the daily rows
   after "Reprocess history". Not folded into reprocess, which would undo an
   admin's explicit "competitive" choice.
2. **Paraphrases rotate by run.** Sample 0 is the canonical text; extra
   samples take `pool[(r - 1 + run_id) % len]`, so a two-sample plan reaches
   every paraphrase over consecutive runs (before, the second paraphrase never
   ran). The wording asked is stored as `results.asked_text` (m38). The claim
   that pooled paraphrases make the rate "reflect the topic" is withdrawn: the
   controlled studies find rewording moves brand sets more than rerunning, so
   constraint-changing wordings become their own questions in a later step.
3. **Tenant geo reaches every SERP capture.** Missing keys are filled from
   `DEFAULT_AIO_GEO` (ca/en); AI Mode's direct-call fallback was "us".
4. **Access audit grades per crawler.** The user-agent A/B now probes
   OAI-SearchBot, PerplexityBot, Claude-SearchBot and bingbot (search class,
   "fail" on refusal) and GPTBot (training, "warn" only): since Cloudflare's
   2026-09-15 defaults, a GPTBot 403 beside a browser 200 is normal and says
   nothing about live answers. Googlebot and Meta-ExternalFetcher join the
   robots check; it is still homepage-only. JSON-LD absence is advisory
   (Ahrefs May 2026: no citation effect).
5. **Playbook order follows the evidence**: access gate → facts and
   freshness → earned → formatting. AIO 80, connect-logs 72/60, crawler
   absent 95, reviews 66, read-not-cited 62; broken-page and log plays graded
   moderate (product rationale, not a study). The sub-search plays cite the
   controlled study (arXiv 2605.25517) with the vendor data marked
   correlational. Word count is no longer a gap (r ≈ 0.04); a 250-word floor
   is. The spam check flags self-ranked list forms, not comparisons. The
   drafter writes "for a reader who wants the facts". Dated claims fixed:
   Google's spam policy change 2026-05-15 enforced June and August; "Bing
   feeds ChatGPT" is "by most accounts"; Muse markets.
6. **Engine priority by use** (Similarweb Sept 2026 visits: ChatGPT 56%,
   Gemini 25%, Claude 10%, Perplexity <1%): ChatGPT, Gemini, Google AIO,
   Claude, Google AI Mode, Perplexity, then web and Meta surfaces. Monitor
   now keeps ChatGPT, Gemini and Google AIO.
7. **Unforced probe on every question for Diagnose and Command**
   (`PlanLimits.natural_probe_fraction` = 1.0; Monitor and Custom keep the
   deployment setting). About $20–25 a month for 50 questions at 3×/week.
8. **Headline is generic answers only.** `mention_rates`, `kpi_scorecard` and
   `topic_scorecard` filter `persona_segment IN ("generic", "")`; persona
   answers stay on the Personas page. Clients without a generic cell keep all
   segments (`segment: "all"` in the payload). Rates move for every client
   that runs personas. The denominator (all answers, including those naming
   no brand) is now stated on the scorecard and in the report.
9. **Engine changes are annotated where they matter.** Series breaks added
   for 2026-10-08 and 2026-10-29 (ChatGPT web), 2026-10-15 (AI Overviews and
   AI Mode link layout) and 2026-10-28 (AI Mode ads, Canadian tenants only).
   `engine_breaks()` feeds the trend notes, alerts and proof: an alert whose
   engine changed says so, the pooled verdict is withheld while a break is in
   the window, and proof keeps each changed engine's answers only from the
   state the fix shipped in (last change before the ship date to first change
   after), reporting "confounded" when that leaves no readable lift. Dropping
   the whole engine was tried first and left nothing in a season with this
   many changes.
10. **Alerts use Holm.** The alert bar corrects across Overall plus every
    engine per call; scorecard rows keep the per-row p < 0.05 label, so the
    bar is stricter than the table on purpose.
11. **Small fixes.** Low reasoning pinned for GPT-6 as well as GPT-5; the
    schedule default and readiness hint say `0 12 * * 1,3,5` (M52); GA4's
    ChatGPT tagging gap is Oct 8–16; the cadence copy is a cost statement.
12. **Not rewritten.** Citations the sweep could not re-verify (the notes
    behind them were lost with the container) stay until checked against
    their originals: arXiv 2606.17443 and 2605.27439, Peec/Writesonic,
    Qwairy, the SEL September experiments, the 30-day churn figure, Profound's
    Muse figures, "19+ data points".

## M54 — Muse as an import-only surface; Muse steps in the Meta play (2026-10-31)

1. **`meta_muse` surface, imported captures only** (migration m37). Closes the
   gap left open in M53: Muse needs a signed-in account, so its answers come
   from a vendor that tracks it, through capture import, and are measured like
   any other answer. It's never dispatched, so it needs no key, plan slot or
   switch; readiness shows "import only" until captures arrive, then
   "imported". Captures carry no search count, so dashboards treat it like the
   browser surfaces (a cited source is the evidence it searched).
2. **"Close the gap on Muse"** fires on the same test as the Meta AI play
   (two-proportion, against other engines' unforced answers). Steps follow the
   reported Muse behaviour: get stocked by well-known retailers, grow branded
   demand, product pages readable as plain text, agentic checkout on the
   catalog. Evidence "emerging": one small study and a reported instruction
   file (WHY["muse"]).
3. **The Meta AI play gains the first two Muse steps** for brands that sell
   products, since Muse shops on the same model and most tenants won't have
   Muse imports yet.

## M53 — Meta AI: reasoning pinned low (2026-10-31)

1. **`reasoning.effort = "low"` on every Muse Spark call.** Muse Spark can't
   turn reasoning off, the API default is medium or higher, and reasoning
   tokens come out of `max_output_tokens` before the answer. Third-party
   integrations hit this at small caps (a 512-token cap with medium effort left
   3 tokens of answer). Our cap is 1,200, so unpinned calls risked cut-off
   answers that read as "brand not named". Low also matches the app: Instant
   (fast, light) is the default and Thinking is opt-in. Same pin as GPT-5.
2. **Known gap, not fixed here: Muse, the agent.** Muse (US since 2026-09-08, Singapore since
   2026-10-28, not in Canada as of 2026-10-31; muse.ai and WhatsApp) is a separate signed-in agent that browses and shops.
   Reported behaviour (Profound, Oct 2026, small sample): most product picks
   come from browsing the open web, not Meta's catalog; well-known merchants
   rank first; a named brand's own store goes to the top. The API can't reach
   it and we don't automate signed-in accounts, so it can only come in through
   capture import from a vendor that tracks it. (Done in M54.)

## M52 — Run cost: re-probe ceiling 75 → 15, 3×/week cadence (2026-10-31)

1. **Command and Custom re-probe ceiling cut from 75 to 15 per run** (same as
   Diagnose; K per prompt stays 5). Full GoDaddy runs were costing ~$15, and
   the cost model put roughly half of that on the fan-out re-probe (75 probes
   at ~$0.12, mostly Gemini grounding). Perplexity's API was ~4%, so it stays.
   The 7-day TTL still rotates coverage across the shard set, just slower.
2. **Recommended schedule is 3×/week** (`0 12 * * 1,3,5`), not daily. Daily at
   ~$15 is ~$450/month per tenant, far over the $50 default cap, so calls get
   WITHHELD mid-month and the trend gets holes. The schedule is a per-tenant
   admin setting; the demo checklist now says 3×/week.

## M51 — Meta AI as a measured engine (2026-10-30)

1. **The model, not the app.** "Meta AI (API)" (`meta_api`) calls Muse Spark,
   the model the Meta AI app serves, through the Meta Model API
   (`api.meta.ai/v1/responses`, public preview) with its `web_search` tool.
   The app can also search Facebook, Instagram and Threads posts and product
   catalogs, and the Muse shopping agent acts inside WhatsApp; neither is
   reachable by API, so labels say "API". Scraping meta.ai needs a logged-in
   account and stays out (no in-house logged-in scraping).
2. **Search offered, not forced**, like Claude and Gemini: the app decides
   when to search, and `tool_choice` on this API is undocumented. Its answer
   is already "what users see", so it gets no separate unforced probe.
3. **Built without a live call.** This session's network blocked Meta's API
   and docs, so the request and response follow the documented
   OpenAI-compatible shape (confirmed by LiteLLM's provider config and price
   list). A cited answer with no listed search step counts as one search.
   The engine check on the worker is the first real test.
4. **Model and price.** `muse-spark-1.3` on every tier, $1.25 / $4.25 per 1M
   tokens and $2.50 per 1k searches (LiteLLM, OpenRouter). Never a
   "-contributor" model: Meta trains on those prompts and answers.
5. **Meta's search crawler** (`meta-webindexer`, listed by Meta for Meta AI
   search) is now classified in AI Agents and checked in the robots audit.
6. **Play:** "Close the gap on Meta AI" fires only when Meta names the brand
   significantly less often than the other engines' unforced answers
   (two-proportion test, 30+ answers a side). Evidence graded "emerging".
7. Migration m36 adds the enum value; verified on a blank Postgres.

## M50 — ChatGPT tracking outage, Oct 8–15 (2026-10-21)

1. **A dated note, not an estimate.** ChatGPT's links went untagged from
   about 2pm Pacific on Oct 8 until a fix rolled out on Oct 15 (reported by
   Adobe's Cedric Huesler and by Profound), so GA4 filed those clicks under
   Direct, permanently. The Outcome chart greys those days and says the dip
   is missing data. The "AI referral sessions" row under each fix (web, PDF
   and workbook) says when its window includes the outage. No attempt to
   estimate the hidden visits.
2. **One list of known gaps** (`TRACKING_GAPS` in `engine/analytics/ga4.py`),
   so the next outage is a one-line addition.
3. **PDF bug found on the way:** the proof table crashed the report for any
   client with GA4 connected and a fix logged (the referrals row has no
   control), and for a fix whose question had no answers before it shipped.
   Both now render a dash (regression test added).

## M49 — Plain-language pass (2026-10-21)

1. **Copy.** Swept every page, the PDF report, recommendation reasons and
   briefing text for generated-sounding writing: "not X, it's Y" reveals,
   rhetorical questions, filler adverbs, invented labels and stacked em
   dashes. Internal terms the client never needs ("variant", "tenant",
   "shard", "forced search" unexplained) are replaced with what they mean.
   The landing page says what the product does in two short paragraphs.
2. **No uncredited figures.** A "why" line names its source (the study or
   vendor and year) or says what kind of evidence backs it. Claims the
   sources don't support were cut back to what they do say.
3. **Design.** Removed the all-caps tracked labels and most section
   eyebrows (labels are sentence case now), the status dots, decorative
   glows and blur, and the hatched row texture. Pills are 4px rectangles.
   The colour rules are unchanged: orange for the brand and good news, ink
   for bad news.
4. **Cost is admin-only.** Run and answer cost no longer shows on client
   pages; admins still see it.
5. **Phones get the client switcher.** The mobile header shows the org
   switcher the sidebar has on desktop.
6. **Bug found on the way:** the playbook builder had no fallback entry for
   the site-search and primary-source plays, so if either raised, run
   processing failed. Now a failing source keeps its last plays and the
   rest of the playbook builds (regression test added).
7. **Features left alone.** Cutting or merging pages is the owner's call;
   the candidates are listed for a decision, not removed.

## M48 — Fan-out simulator (2026-10-21)

1. **A replay, not a cartoon.** The simulator on the Fan-out page plays back a
   real answer from the latest runs: the question, the sub-searches the
   engine reported, what a re-run of each found (you / which rivals / no
   brand), and the answer (named or not, rank, rivals, cited sources). It
   teaches what fan-out is with the client's own data.
2. **No guessing.** A sub-search we never re-ran says "not re-checked yet";
   `site:` searches say whose site was searched instead of a result.
3. **Four beats** (question, split, searches, answer) with Play, Step, Reset
   and clickable step markers; transitions respect reduced motion. On phones
   it stacks vertically without the connector lines.
4. Demo client: a second question (bakery) with a mixed fan-out (one won,
   one lost to Siteforge, one open) so the demo shows all three outcomes.

## M47 — What users see, where engines check, and primary sources (2026-10-21)

From October research (Ahrefs' 66.6M-answer ChatGPT study, Oct 12; a 2026
preprint on what drives citations):

1. **"Without forced search" beside the headline.** ChatGPT and Perplexity
   are forced to search on every measured answer, but free ChatGPT searched in
   about one answer in seven in that study (free, logged-out, GPT-5.6 Luna,
   Aug–Sep 2026: a floor; Semrush put it at a third in Feb 2026, paid tiers
   near always). Their unforced probe is now a
   rate with a range and a search share, per engine and pooled. The pooled
   figure is withheld until every forced engine has unforced answers, since a
   partial pool would mislead. The headline itself is unchanged (comparable
   series). The probed third of questions now rotates per run so all
   questions get unforced answers.
2. **Bug fixed: mentions on probe and no-search answers.** Only forced-search
   answers had mentions extracted, so "named from memory" (Engines) read 0%
   for forced engines and the training diagnosis never saw the brand. All
   scores still filter to search answers. Agent picks now filter to search
   answers too (the extra variants were diluting the pick rate).
3. **Site searches.** `site:` sub-searches are counted by target: your
   domains, rivals', others. Shown on Your Pages with what was looked up, and
   a play when rivals' sites are searched at least twice as often (minimum 5).
   Branded questions are excluded (they send engines to your site by design).
4. **Research as a source type** (studies, journals, .gov/.edu, official
   statistics), with a play when it is a real share of citations (at least 3
   and 8%). The "get onto these publishers" play no longer suggests government
   or journal domains.
5. **Fix:** bad-news chips rendered white on white (`.chip` reset the ink
   pill background).

## M46 — A client report worth handing over, and a data workbook (2026-10-05)

1. **The PDF is HTML rendered by WeasyPrint.** fpdf2 drew plain text lines;
   designing a report there means hand-placing every box. The report is now a
   Jinja template (`api/report_assets/report.html`) in the Ledger design:
   Inter, navy cover, orange for the brand and good news, ink pills for bad
   news. Charts are inline SVG built in Python (static, since it's print).
2. **Same sources as the dashboard.** Every section calls the service its
   page uses (briefing, KPI scorecard, citations, own pages, fan-out, agent
   picks, playbook, proof), so the PDF never disagrees with the app. Each
   section is built separately: one failure shows an empty state, not a
   broken report.
3. **EverPresent branding only** (the user's call); no agency white-label yet.
4. **Fallback.** WeasyPrint needs Pango. Both images install it; if the
   libraries are ever missing, `build_summary_pdf` logs and sends the old
   one-page summary, so downloads and run emails never fail.
5. **Excel workbook** (`/reports/report.xlsx`): a tab per dataset, full
   lists rather than the report's top-N. Cells starting with `=` are forced
   to text so answer or page text can never run as a formula.

## M45 — Fan-out from four engines, and reprocess history (2026-10-05)

1. **Who reports their searches.** ChatGPT (the Responses API's search
   actions, now including batched `queries`), Gemini (grounding
   `webSearchQueries`), Perplexity (search `queries`) and now Claude
   (`server_tool_use` web_search blocks, previously ignored). Google AI
   Overviews, AI Mode and the browser captures don't expose their searches,
   so they have no fan-out.
2. **History catches up for free.** Processing re-reads Claude and ChatGPT
   searches from each stored raw response, and admin → "Reprocess history"
   re-runs processing over every completed run on the worker. No new answers
   are bought.

## M44 — A fictional demo client with a real playbook (2026-10-05)

1. **Northpeak**, a made-up website builder on `northpeak.example`, with four
   made-up rivals. `.example` never resolves, so nothing real is crawled,
   quoted or accused. Admin → "Build demo client" queues the build on the
   worker; rebuilding wipes only that tenant's data (not its login link).
2. **Real pipeline, seeded inputs.** The builder writes raw answers, bot
   logs, page checks, Search Console rows and one logged fix, then runs the
   normal processing and playbook. Every play is derived from data a viewer
   can open. The one shortcut: the web-search classifier needs no-search
   twin answers, so each question's class is set directly.
3. **Checked for legitimacy.** Tests assert each story beat produces its play
   (wrong $19 price traced to /help/plans, missing Claude-SearchBot,
   PerplexityBot refusals, a lost and erroring cost guide, a dead
   /old-pricing, a read-but-never-cited page, a ChatGPT model switch, a proven
   fix) and that no play gives advice the data doesn't support.
4. **Safety.** Spend cap 0 (no paid runs on a fictional brand), AI processing
   off, and the nightly page crawl skips it.
5. **Product fix found on the way.** Page "errors" on AI Agents and Your
   Pages no longer count refusals (401/403/407/429): a page blocked for one
   bot is an access problem for that bot's play, not a dead page to redirect
   or an "erroring" cited page.

## M43 — "Ledger" design: built like a finance product (2026-10-05)

1. **Replaces "Studio".** The warm paper ground, serif display and soft
   shadows read as generic AI-product styling. Ledger uses a cool neutral
   ground, white panels with crisp 1px rules and almost no shadow, tight
   corners (10px panels, 6px controls) and a deep navy sidebar that stays
   dark in both themes.
2. **Type.** Inter (self-hosted, OFL) everywhere with tabular figures; the
   serif is gone. Labels and table heads are small uppercase with tracking,
   as on a statement. Dates read "Oct 4, 2026".
3. **Overview hero.** A balance-style card: the mention rate as the big
   figure, its range, a status pill (gaining, losing, holding steady,
   building baseline) and an area sparkline of the visibility score, with a
   stat strip under it. Status pills follow the existing colour rule:
   orange for good news, ink for bad, grey otherwise.
4. The sample-size planner no longer prints a multiplier for an engine with
   under 10 answers per half window ("too few answers to plan yet").

## M42 — Dashboard reads split by page (2026-10-04)

1. `api/dashboards_service.py` (about 2,700 lines) is now the package
   `api/dashboards/`, one module per page: common, overview, citations,
   engines, fanout, brand, measurement, outcome, action_plan, queries.
2. **A pure move.** Every function and constant was moved verbatim (checked
   mechanically against the old file); no behaviour changed. The module
   graph has no cycles.
3. **Old imports keep working.** `api.dashboards_service` re-exports every
   name, private helpers included, so other services and tests are
   untouched. New code should import from `api.dashboards.<page>`.

## M41 — Signed-in pages in CI, and an honest "API down" state (2026-10-04)

1. **Every signed-in page in CI.** Job `signed-in-pages` migrates a SQLite
   database, seeds the GoDaddy config with nine synthetic runs (processed
   normally, plus one logged fix), strips Clerk from the throwaway checkout
   (`scripts/e2e/strip_clerk.py`), and serves the API with the auth
   dependency overridden (`scripts/e2e/serve_api.py`). Playwright then loads
   all 16 dashboard pages and both admin pages, failing on HTTP errors,
   browser exceptions, error text or the "no organization" state.
2. **Production code is untouched.** The bypass exists only in scripts/e2e
   and only runs in that job. The strip script stops the job if Clerk is
   still imported anywhere, so a new Clerk call can't slip through untested.
3. **Found while building it:** with the API unreachable, pages fell back to
   empty states ("No scorecard yet") that read like "no data". Dashboard and
   admin layouts now check API health once per page and show an "Offline"
   banner, and the test fails on it.

## M40 — Vendor capture import (2026-10-04)

1. **We import signed-in answers; we don't log in.** Automating signed-in
   consumer accounts breaks those services' terms, so signed-in (and any
   other outside) captures come from a vendor as JSON. Admin uploads the
   file; each import becomes a run with trigger "import" and is processed
   like our own: mentions, citations, accuracy, sponsored units.
2. **Format.** `{source, captures: [{surface, query, answer_html | answer,
   citations, captured_at, logged_in, model, persona, location}]}`. HTML is
   preferred because ads are cut from it before counting. The capture date
   becomes the result date, so imports land on the right day in trends.
3. **Safety.** Superadmin only, 25 MB and 5,000 captures per file, known
   surface codes only, http(s) citations only, no future dates (10 minutes
   of clock slack), no empty answers. One bad capture rejects the whole
   file, so nothing half-imports.
4. **Idempotent.** A capture with the same surface, query and answer text
   already on file is skipped, and a file with nothing new leaves no run.

## M39 — Ads kept out of organic visibility (2026-10-04, migration m35)

1. **Cut before counting.** Every browser capture goes through
   `split_sponsored_html` before text and links are extracted: a block
   marked as an ad by its attributes, or the smallest block (up to four
   levels) holding both a standalone "Sponsored"/"Ad" label and a link, is
   removed. Prose that uses the word "sponsored" is never cut. So a paid
   unit can't add a mention, a citation or share of voice.
2. **Stored apart.** Units go to `sponsored_units` (regenerated on
   reprocess): from captured answer HTML, the AI Overview block, and the ad
   blocks SerpApi returns for AI Mode. Each is attributed to the brand or a
   competitor by name or domain, else to its own domain.
3. **Reported apart.** Engines shows the share of answers that came with
   an ad, per engine, and each advertiser's share of units, with the
   brand's share called out.
4. **Old captures** keep their stored text; only new captures are cut.
   Browser engines run signed out, so this is what a logged-out visitor sees.

## M38 — Proof of results (2026-10-04)

1. **Equal windows, one control each.** Each logged fix is compared over the
   same number of days before and after its ship date (up to 28; the ship
   day itself is excluded), and each signal against its own control: answers
   on untouched non-branded questions, and every other page for page counts.
2. **Only the answer change is called real.** Mentions get the
   two-proportion test plus a difference-in-differences against the control.
   Bot reads and Search Console/Bing AI impressions are directional counts
   ("up vs control" needs a 20-point gap over the control's % change). GA4
   AI referrals are sitewide and labelled context, never proof.
3. **Statuses.** Measuring (under 7 days after), real lift, early signal
   (page counts up, answers not yet), no change, down. A fix with no answers
   before it says there's no baseline instead of inventing one, and a page
   that only appears in the data after the fix reads "no baseline", not "new".
4. **Where.** Top of Outcome, shown even before GA4 is connected.

## M37 — Agent picks (2026-10-04)

1. **Being chosen, not just named.** Queries tagged `corpus: agent_task`
   ("register a domain for my bakery") or `corpus: agent_code` ("write a
   script that registers a domain") are measured for which tracked brand the
   answer names first (mention rank 1). The rate reads against every answer,
   with a 95% range; answers that pick no tracked brand count as "no pick".
2. **No new schema.** The prompt type rides on the existing corpus tag, so
   configs and imports work unchanged. Agent prompts were later taken out of
   the competitive numbers (commit 9cc92dd, 2026-10-06; see M47) and scored
   as their own category.
3. **GoDaddy seed** gains three task and two coding prompts (generic
   persona only, to keep the cost small).
4. **Briefing.** When the top rival's first-pick rate sits above the top of
   the brand's range, the briefing lists it ahead of softer reasons.

## M36 — Draft a config from a domain (2026-10-04)

1. **Draft, never import.** Admin "Draft" reads the brand's homepage (public
   addresses only, every redirect hop) and asks the draft model for a config
   in the import format. The draft must pass the same schema as an import,
   then lands in the paste box for a person to edit. Importing stays a
   separate click.
2. **What a draft leaves out.** No brand facts: a wrong fact read off a
   marketing page would raise false accuracy alerts on every run. No engine
   switches: a draft never turns surfaces on or off. The geo is set from the
   request, and the drafted domain is always the first brand domain.
3. **Checks on the draft.** It warns when there's no generic baseline
   persona and when a category question names the brand (that would inflate
   the mention rate).
4. **Cost and abuse.** Superadmin only, booked in the spend ledger as
   `config_draft`, held to the monthly cap and 10 drafts an hour per tenant.
   Homepage text is treated as data in the prompt and can only shape a draft
   that a person reads.

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
   3×/week rather than daily: it keeps a Diagnose client under its cap; daily
   would detect changes about a third smaller (M55 corrects the earlier
   "more samples per dollar" wording, which read as a signal claim).
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
   new users; Gemini 4 "Argon" (announced 2026-09-30) reached general availability
   on 2026-10-13 (API; AI Mode for paid tiers); not pinned yet.
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
   (Superseded by M52: Command and Custom ceilings are now 15.)
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
