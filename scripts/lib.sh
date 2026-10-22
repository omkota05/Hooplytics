#!/usr/bin/env bash
# Shared helpers for Hooplytics scripts.

info() { printf '\033[1;34m[hooplytics]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[hooplytics] error:\033[0m %s\n' "$*" >&2; exit 1; }

find_python() {
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        echo "$candidate"; return 0
      fi
    fi
  done
  return 1
}

check_prereqs() {
  PYTHON_BIN="$(find_python)" || fail "Python 3.11+ is required. Install it from https://www.python.org/downloads/ or with Homebrew (brew install python@3.13)."
  command -v node >/dev/null 2>&1 || fail "Node.js 20+ is required. Install it from https://nodejs.org/ or with Homebrew (brew install node)."
  node -e 'process.exit(parseInt(process.versions.node) >= 20 ? 0 : 1)' || fail "Node.js 20+ is required (found $(node --version))."
  command -v npm >/dev/null 2>&1 || fail "npm is required (it ships with Node.js)."
  command -v docker >/dev/null 2>&1 || fail "Docker is required for the local PostgreSQL database. Install Docker Desktop: https://www.docker.com/products/docker-desktop/"
  export PYTHON_BIN
}

ensure_docker_running() {
  if ! docker info >/dev/null 2>&1; then
    if [[ "$(uname)" == "Darwin" ]] && [[ -d /Applications/Docker.app ]]; then
      info "Docker is not running; starting Docker Desktop..."
      open -a Docker
      for _ in $(seq 1 60); do
        docker info >/dev/null 2>&1 && return 0
        sleep 2
      done
    fi
    fail "Docker daemon is not running. Start Docker Desktop and retry."
  fi
}

start_db() {
  ensure_docker_running
  [[ -f "$ROOT/.env" ]] || fail "Missing .env. Run: make setup"
  info "Starting PostgreSQL (docker compose)..."
  docker compose --env-file "$ROOT/.env" -f "$ROOT/docker-compose.yml" up -d --wait postgres >/dev/null \
    || fail "PostgreSQL container failed to start. Check: docker compose logs postgres"
}
