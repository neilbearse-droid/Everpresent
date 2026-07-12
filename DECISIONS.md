# Decisions of record

Spec §11.7: when the spec is ambiguous, choose the smaller interpretation and
note it here.

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
