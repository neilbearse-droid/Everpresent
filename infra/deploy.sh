#!/usr/bin/env bash
# Deploy EverPresent v3 to the VPS over SSH.
#
# Usage:
#   DEPLOY_HOST=user@vps ./infra/deploy.sh            # update existing deploy
#   DEPLOY_HOST=user@vps ./infra/deploy.sh bootstrap  # first-time setup
#
# Expects on the VPS: docker + docker compose plugin, and /opt/everpresent/.env
# populated from .env.example (secrets never live in the repo, §9).
set -euo pipefail

DEPLOY_HOST="${DEPLOY_HOST:?Set DEPLOY_HOST=user@host}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/everpresent}"
REPO_URL="${REPO_URL:-git@github.com:neilbearse-droid/Everpresent.git}"
BRANCH="${BRANCH:-main}"

if [[ "${1:-}" == "bootstrap" ]]; then
  ssh "$DEPLOY_HOST" bash -s <<EOF
    set -euo pipefail
    sudo mkdir -p "$DEPLOY_DIR" && sudo chown "\$(whoami)" "$DEPLOY_DIR"
    git clone --branch "$BRANCH" "$REPO_URL" "$DEPLOY_DIR" 2>/dev/null || true
    cd "$DEPLOY_DIR"
    if [[ ! -f .env ]]; then
      cp .env.example .env
      echo ">>> Edit $DEPLOY_DIR/.env with real secrets, then re-run deploy. <<<"
      exit 1
    fi
EOF
fi

ssh "$DEPLOY_HOST" bash -s <<EOF
  set -euo pipefail
  cd "$DEPLOY_DIR"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git reset --hard "origin/$BRANCH"
  docker compose --env-file .env -f infra/docker-compose.yml build
  docker compose --env-file .env -f infra/docker-compose.yml up -d postgres redis
  # Migrations run before the app comes up; seed is idempotent (superadmin +
  # launch tenants with their YAML configs, only when absent).
  docker compose --env-file .env -f infra/docker-compose.yml run --rm api alembic upgrade head
  docker compose --env-file .env -f infra/docker-compose.yml up -d
  docker compose --env-file .env -f infra/docker-compose.yml exec -T api python -m api.seed
  docker compose --env-file .env -f infra/docker-compose.yml ps
EOF

echo "Deployed to $DEPLOY_HOST:$DEPLOY_DIR"
