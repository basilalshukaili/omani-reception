# Omani Reception — developer workflow shortcuts
# Works on bash (Git Bash on Windows). PowerShell users: run the commands directly.

.PHONY: help install dev up down logs ps test lint type format check ingest chat health clean

help:
	@echo "Omani Reception — make targets"
	@echo ""
	@echo "  install      Install runtime deps via uv (or pip)"
	@echo "  dev          Install runtime + dev deps"
	@echo "  up           docker-compose up -d (Postgres + Redis + app)"
	@echo "  down         docker-compose down"
	@echo "  logs         tail compose logs"
	@echo "  ps           list compose services"
	@echo "  test         pytest"
	@echo "  lint         ruff check"
	@echo "  format       ruff format"
	@echo "  type         mypy engine"
	@echo "  check        lint + type + test (CI mirror)"
	@echo "  health       python -m engine.cli health"
	@echo "  ingest       python -m engine.cli ingest --business generic_demo"
	@echo "  chat         python -m engine.cli chat --business generic_demo"
	@echo "  clean        remove __pycache__ and caches"

install:
	uv sync --no-dev || pip install -e .

dev:
	uv sync || pip install -e ".[dev]"

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f --tail=100

ps:
	docker-compose ps

test:
	pytest

lint:
	ruff check engine tests

format:
	ruff format engine tests

type:
	mypy engine

check: lint type test

health:
	python -m engine.cli health

ingest:
	python -m engine.cli ingest --business generic_demo

chat:
	python -m engine.cli chat --business generic_demo

clean:
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage 2>/dev/null || true
