.PHONY: setup seed dev dev-backend dev-frontend test demo lint openapi eval

PYTHON ?= python3
VENV := backend/.venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

setup:
	test -f .env || cp .env.example .env
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e "./backend[dev]"
	cd frontend && npm install

seed:
	cd backend && .venv/bin/python -m app.db.seed --world base

dev: ## start API (:8000) and console (:5173)
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/pytest -q

eval:
	cd backend && .venv/bin/python -m evals.run --suite all --repeat 3 --llm fake

demo:
	@echo "Prompt 8 will wire a terminal demo. For now:"
	@echo "  make setup && make dev"
	@echo "  curl -s http://localhost:8000/health"

lint:
	cd frontend && npx tsc -b --pretty false

openapi:
	cd backend && .venv/bin/python -c "from app.main import app; import json, pathlib; pathlib.Path('../frontend/openapi.json').write_text(json.dumps(app.openapi(), indent=2))"
	cd frontend && npm run gen:api


PYTHON ?= python3
VENV := backend/.venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

setup:
	test -f .env || cp .env.example .env
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e "./backend[dev]"
	cd frontend && npm install

seed:
	cd backend && .venv/bin/python -m app.db.seed --world base

dev: ## start API (:8000) and console (:5173)
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/pytest -q

eval:
	cd backend && .venv/bin/python -m evals.run --suite all --repeat 3 --llm fake

demo:
	@echo "Prompt 8 will wire a terminal demo. For now:"
	@echo "  make setup && make dev"
	@echo "  curl -s http://localhost:8000/health"

lint:
	cd frontend && npx tsc -b --pretty false
