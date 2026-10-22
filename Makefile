.PHONY: start restart stop logs build test setup backend frontend database format check check-docs monitor evaluation-dashboard dashboards evaluation-setup evaluation-import evaluate fresh-start pricing-refresh

PYTHON ?= python3
PNPM ?= pnpm

start:
	@sh scripts/start.sh

restart:
	docker compose up --no-build --force-recreate -d --wait --wait-timeout 120

stop:
	docker compose down

logs:
	docker compose logs -f

build:
	@REBUILD=1 BUILD_ONLY=1 sh scripts/start.sh

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -r backend/requirements-dev.txt
	cd frontend && $(PNPM) install --frozen-lockfile

test: database
	mkdir -p resources/tests
	PYTHONPATH=backend .venv/bin/python -m pytest backend/tests -q --basetemp=resources/tests/pytest
	cd frontend && $(PNPM) build

backend:
	.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload

frontend:
	cd frontend && $(PNPM) dev

format:
	.venv/bin/ruff format
	cd frontend && $(PNPM) format:chat

check:
	.venv/bin/ruff check
	.venv/bin/ruff format --check
	cd frontend && $(PNPM) check:chat-format

check-docs:
	$(PYTHON) scripts/check-docs.py

database:
	mkdir -p resources/mongodb resources/mongodb-config
	docker compose up -d --wait mongodb

monitor:
	.venv/bin/python scripts/dashboards.py monitoring

evaluation-dashboard:
	.venv/bin/python scripts/dashboards.py evaluation

dashboards:
	.venv/bin/python scripts/dashboards.py all

evaluation-setup:
	$(PYTHON) -m venv .venv-evaluation
	.venv-evaluation/bin/python -m pip install -r backend/requirements-evaluation.txt

DOCUMENT ?= $(HOME)/Downloads/Conversation.docx
CONNECTION ?=
DATASET ?=
RAGAS ?= 0
JUDGE_CONNECTION ?=
EFFORT ?= standard
EVAL_BASE ?= http://127.0.0.1:8000

evaluation-import:
	PYTHONPATH=backend .venv/bin/python -m app.observability.evaluation --document "$(DOCUMENT)" --import-only

evaluate:
	PYTHONPATH=backend .venv-evaluation/bin/python -m app.observability.evaluation --document "$(DOCUMENT)" --base "$(EVAL_BASE)" $(if $(CONNECTION),--connection "$(CONNECTION)") $(if $(DATASET),--dataset "$(DATASET)") $(if $(filter 1,$(RAGAS)),--ragas) --effort "$(EFFORT)" $(if $(JUDGE_CONNECTION),--judge-connection "$(JUDGE_CONNECTION)")

fresh-start:
	@echo 'This clears imported tickets, conversations, model settings and the search index. A private backup is kept in resources/app/backups.'
	@printf 'Type RESET to continue: '; read answer; test "$$answer" = RESET
	docker compose stop app
	docker compose run --rm --no-deps --entrypoint python app -m app.workspace_reset --confirm RESET
	@OPEN_BROWSER=0 sh scripts/start.sh

pricing-refresh:
	.venv/bin/python scripts/update-pricing.py
