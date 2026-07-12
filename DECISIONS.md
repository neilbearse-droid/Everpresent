# Decisions of record

Spec §11.7: when the spec is ambiguous, choose the smaller interpretation and
note it here.

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
