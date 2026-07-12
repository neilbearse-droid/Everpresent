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
.venv/bin/uvicorn api.main:app --reload          # http://localhost:8000/api/health

# Frontend (proxies /api to localhost:8000)
cd app && npm install && npm run dev             # http://localhost:3000

# Checks (same as CI)
.venv/bin/ruff check . && .venv/bin/pyright && .venv/bin/pytest
cd app && npm run typecheck && npm run build && npx playwright test
```

Postgres/Redis for local dev: `docker compose -f infra/docker-compose.yml up postgres redis`.
Tests need neither (they run on in-memory SQLite).

## Deploying (single VPS, Docker Compose)

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

The deploy script builds images, brings the stack up, and runs the idempotent
seed (`python -m api.seed`), which provisions the superadmin row for
`SUPERADMIN_EMAIL`. The superadmin's Clerk account is linked to that row on
first login.

## Milestones

Built one milestone at a time with a human review gate between each — see the
v3 spec. Current: **M0** (repo, CI, compose stack, deploy script, seeded
superadmin). Decisions of record live in `DECISIONS.md`.
