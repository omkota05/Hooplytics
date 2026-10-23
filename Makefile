SHELL := /bin/bash
BACKEND := cd backend && .venv/bin

.PHONY: help setup dev db db-stop db-reset migrate migration sync backfill status test lint typecheck build check export-dataset ml-train ml-metrics ml-predict ml-prepare ml-train-games ml-metrics-games ml-predict-game

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## One-time setup: env files, Python venv, npm install
	@bash scripts/setup.sh

dev: ## Start PostgreSQL, API (with auto-sync) and frontend
	@bash scripts/dev.sh

db: ## Start the PostgreSQL container
	@ROOT=$(CURDIR) bash -c 'source scripts/lib.sh && start_db && info "PostgreSQL is up on port $${POSTGRES_PORT:-5433}"'

db-stop: ## Stop the PostgreSQL container (data is kept)
	docker compose --env-file .env stop postgres

db-reset: ## DANGER: delete the local database volume and all synced data
	@read -p "Delete all local Hooplytics data? [y/N] " ans && [[ $$ans == y ]]
	docker compose --env-file .env down -v

migrate: ## Apply database migrations
	$(BACKEND)/alembic upgrade head

migration: ## Create a migration: make migration m="describe change"
	$(BACKEND)/alembic revision --autogenerate -m "$(m)"

sync: ## Incremental sync now (new games, box scores, schedule, rosters)
	$(BACKEND)/python -m app.cli sync

backfill: ## Download historical seasons (resumable; HISTORY_SEASONS in backend/.env)
	$(BACKEND)/python -m app.cli backfill

status: ## Show data freshness and per-season coverage
	$(BACKEND)/python -m app.cli status

export-dataset: ## Export leakage-safe ML feature table: make export-dataset out=data.csv
	$(BACKEND)/python -m app.cli export-dataset $(or $(out),player_games.csv)

ml-prepare: ## Export enriched ML dataset to backend/artifacts/ml/dataset.parquet
	@mkdir -p backend/artifacts/ml
	$(BACKEND)/pip install -q -r backend/requirements-ml.txt
	$(BACKEND)/python -m app.cli export-dataset backend/artifacts/ml/dataset.parquet

ml-train: ## Train player stat models (needs `make db` and synced history)
	$(BACKEND)/pip install -q -r backend/requirements-ml.txt
	$(BACKEND)/python -m app.cli ml-train

ml-metrics: ## Show MAE/RMSE backtest metrics for active models
	$(BACKEND)/python -m app.cli ml-metrics

ml-predict: ## Example: make ml-predict player=1966 game=401909842 stat=pts_reb_ast line=30.5
	$(BACKEND)/python -m app.cli ml-predict --player-id $(player) --game-id $(game) --stat $(stat) --line $(line)

ml-train-games: ## Train game-winner model (needs `make db` and synced history)
	$(BACKEND)/pip install -q -r requirements-ml.txt
	$(BACKEND)/python -m app.cli ml-train-games

ml-metrics-games: ## Show held-out metrics for game-winner model
	$(BACKEND)/python -m app.cli ml-metrics-games

ml-predict-game: ## Example: make ml-predict-game game=401234567
	$(BACKEND)/python -m app.cli ml-predict-game --game-id $(game)

test: ## Run backend tests (DB tests need `make db`)
	$(BACKEND)/pytest

lint: ## Lint backend and frontend
	$(BACKEND)/ruff check app tests
	cd frontend && npx eslint src

typecheck: ## TypeScript type check
	cd frontend && npx tsc --noEmit

build: ## Production build of the frontend
	cd frontend && npm run build

check: lint typecheck test ## Lint, type check, and test everything
