# EverPresent v3

Multi-tenant SaaS for Generative Engine Optimization: measure how visible a
brand is inside AI-generated answers across surfaces and personas, compare
against competitors, and prescribe actions.

Monorepo layout:

| Path | What |
|---|---|
| `app/` | Next.js frontend (Tailwind, Clerk auth) |
| `api/` | FastAPI backend (SQLModel on Postgres) |
| `engine/` | Measurement engine: retrieval, classification, scoring, LLM router |
| `worker/` | RQ workers (API-mode jobs; Playwright scraping worker arrives M4) |
| `infra/` | Docker Compose, Caddy, deploy script |

## Runtime model policy

`claude-fable-5` (and any Mythos-class model) is a **build-time tool only** and
must never appear in runtime configuration. The allowlist lives in
`engine/llm/policy.py`; `tests/test_llm_policy.py` is a merge blocker that
fails the suite if a forbidden model string reaches any runtime config.

## Local development

```bash
# Backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head                   # schema (needs DATABASE_URL, see .env.example)
.venv/bin/python -m api.seed                     # superadmin + launch tenants
.venv/bin/uvicorn api.main:app --reload          # http://localhost:8000/api/health

# Frontend (proxies /api to localhost:8000)
cd app && npm install && npm run dev             # http://localhost:3000

# Checks (same as CI)
.venv/bin/ruff check . && .venv/bin/pyright && .venv/bin/pytest
cd app && npm run typecheck && npm run build && npx playwright test
```

Postgres/Redis for local dev: `docker compose -f infra/docker-compose.yml up postgres redis`.
Tests need neither (they run on in-memory SQLite).

## Deploying

Two supported paths:

- **Managed (Render)** — no server to run. Connect the repo, Render reads
  `render.yaml`, done. Best for a solo operator; ~$55/mo. Walkthrough:
  `RENDER_DEPLOY.md` (+ `CLERK_SETUP.md`, `LAUNCH.md`). Raw payloads live in
  Postgres (`STORAGE_BACKEND=db`) since managed services can't share a disk.
- **Single VPS (Docker Compose)** — cheaper (~$15–25/mo), you run the box.
  Steps below. Raw payloads use a shared volume (`STORAGE_BACKEND=file`,
  default).

### Single VPS (Docker Compose)

One-time:

1. Create a Clerk application (invite-only: disable public sign-ups), enable
   **Organizations**, and copy the publishable key, secret key, and JWKS URL.
2. Point DNS at the VPS; install Docker + the compose plugin.
3. `DEPLOY_HOST=user@vps ./infra/deploy.sh bootstrap`, then fill in
   `/opt/everpresent/.env` from `.env.example`.

Every deploy after that:

```bash
DEPLOY_HOST=user@vps ./infra/deploy.sh
```

The deploy script builds images, runs `alembic upgrade head`, brings the stack
up, and runs the idempotent seed (`python -m api.seed`): the superadmin row
for `SUPERADMIN_EMAIL` (Clerk account linked on first login) plus the two
launch tenants (`smith`, `greenshield`) with their `seeds/*.yaml` configs.

## Tenancy

Clerk organizations map one-to-one to tenants. The API resolves the tenant
from the session token's org claim only — never from a request parameter —
and `tests/test_tenancy.py` is the merge-blocking proof that cross-tenant
reads fail. To wire a tenant up: create the org in Clerk, invite members,
then paste the `org_…` id into the tenant's admin page.

## Milestones

Built one milestone at a time with a human review gate between each — see the
v3 spec. Done: **M0** (repo, CI, compose stack, deploy script, seeded
superadmin), **M1** (tenancy + Clerk orgs, admin panel, YAML config import,
isolation tests), **M2** (Mode A measurement on the OpenAI Responses API:
admin-triggered runs through RQ, results + citations in Postgres, raw
envelopes in object storage, run/result viewers, per-tenant spend caps
enforced pre-dispatch, governance-gated runs recorded rather than skipped).
Real M2 runs need `OPENAI_API_KEY` in the deployment env; CI runs on recorded
fixtures only. **M3** (processing + dashboards: dual-query web-search-likelihood
classifier, mention detection with sentiment and rank, visibility scoring and
daily rollups, Overview/Personas/Queries screens). The M3 processing code is a
v3-native implementation, not the spec-mandated v1 port — see DECISIONS.md M3.1
for why and for the swap procedure if the v1 source surfaces. **M4** (Mode B:
Playwright scrape worker on its own queue/container, chatgpt_web fresh-session
adapter with selectors isolated in one file, A→B chained runs, side-by-side
mode comparison in Queries), **M5** (cron run schedules via a scheduler
service, run-completion email reports with PDF/CSV attached and the 80%
spend alert, report export endpoints + dashboard downloads, nightly BigQuery
mirror of run metadata, Perplexity as the second Mode B adapter). Optional
M5 env: SMTP_* for email, BIGQUERY_* + service-account JSON for the mirror.
**M6** (Google AIO: SERP capture with per-tenant geolocation and a SerpAPI
fallback, GoogleAIOSignal + rule-based classifier — provisional thresholds
pending the §12.1 labeled seed queries, see DECISIONS.md M6.1 — the §6.4
recommendation matrix with web-search/training/AIO branches, and the
Citations screen + AIO share tiles). **That completes the specced milestone
plan (M0–M6).** Decisions of record live in `DECISIONS.md`.
