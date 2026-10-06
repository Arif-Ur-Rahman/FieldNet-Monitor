# One command each: `make up`, `make test`, `make sim`.
# The *-local targets run against a local Postgres and backend/.venv instead of Docker.
COMPOSE ?= docker compose
VENV    ?= backend/.venv/bin
STORY   ?= all

.PHONY: up down logs test sim migrate test-local sim-local lint fmt

up:            ## Start db, api, worker and web
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f api worker

test:          ## Run the backend test suite in Docker
	$(COMPOSE) run --rm --build -e TEST_MODE=1 api pytest

sim:           ## Play simulator stories against the running stack (STORY=name|all)
	$(COMPOSE) run --rm --no-deps -v $(PWD)/simulator:/simulator -e API_URL=http://api:8000 api python /simulator/sim.py $(STORY)

migrate:
	$(COMPOSE) run --rm api python manage.py migrate

test-local:
	cd backend && .venv/bin/pytest

sim-local:
	API_URL=http://localhost:8000 $(VENV)/python simulator/sim.py $(STORY)

lint:          ## Lint backend and simulator with the backend's ruff settings
	cd backend && .venv/bin/ruff check --config ruff.toml . ../simulator && .venv/bin/ruff format --config ruff.toml --check . ../simulator

fmt:
	cd backend && .venv/bin/ruff check --config ruff.toml --fix . ../simulator && .venv/bin/ruff format --config ruff.toml . ../simulator
