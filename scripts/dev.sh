#!/usr/bin/env bash
# Start everything for local development: PostgreSQL, migrations, API (with background
# sync), and the Next.js frontend. Ctrl-C stops the API and frontend; the database
# container keeps running (stop it with `make db-stop`).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/lib.sh"

check_prereqs
[[ -x backend/.venv/bin/python ]] || fail "Backend virtualenv missing. Run: make setup"
[[ -d frontend/node_modules ]] || fail "Frontend dependencies missing. Run: make setup"
[[ -f backend/.env ]] || fail "backend/.env missing. Run: make setup"

for port in 8000 3000; do
  if lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "Port $port is already in use. Stop the other process (lsof -iTCP:$port) and retry."
  fi
done

start_db

info "Applying database migrations..."
(cd backend && .venv/bin/alembic upgrade head) || fail "Migrations failed."

pids=()
cleanup() {
  info "Shutting down..."
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

prefix() { local tag="$1" color="$2"; while IFS= read -r line; do printf '\033[%sm[%s]\033[0m %s\n' "$color" "$tag" "$line"; done; }

info "Starting API on http://localhost:8000 (docs at /docs)..."
(cd backend && exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload 2>&1 | prefix api "1;35") &
pids+=($!)

info "Starting frontend on http://localhost:3000 ..."
(cd frontend && exec npm run dev -- --port 3000 2>&1 | prefix web "1;36") &
pids+=($!)

info "Hooplytics is starting. Open http://localhost:3000"
wait
