#!/usr/bin/env bash
# One-time local setup: checks prerequisites, writes .env files, installs dependencies.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/lib.sh"

check_prereqs

if [[ ! -f .env ]]; then
  password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  sed "s/change_me_local_only/${password}/" .env.example > .env
  sed "s/change_me_local_only/${password}/" backend/.env.example > backend/.env
  info "Wrote .env and backend/.env with a generated local database password."
elif [[ ! -f backend/.env ]]; then
  fail "backend/.env is missing but .env exists. Copy backend/.env.example and set the same POSTGRES_PASSWORD."
fi

if [[ ! -f frontend/.env.local ]]; then
  cp frontend/.env.example frontend/.env.local
  info "Wrote frontend/.env.local."
fi

info "Creating Python virtualenv (backend/.venv)..."
[[ -d backend/.venv ]] || "$PYTHON_BIN" -m venv backend/.venv
backend/.venv/bin/pip install --quiet --upgrade pip
backend/.venv/bin/pip install --quiet -r backend/requirements-dev.txt

info "Installing frontend dependencies..."
(cd frontend && npm install --no-fund --no-audit)

info "Setup complete. Next: make dev"
