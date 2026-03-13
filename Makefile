.PHONY: setup test lint migrate run

setup:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"
	.venv/bin/playwright install firefox

test:
	.venv/bin/pytest tests/ -v

lint:
	.venv/bin/ruff check src/ tests/
	.venv/bin/ruff format --check src/ tests/

format:
	.venv/bin/ruff format src/ tests/
	.venv/bin/ruff check --fix src/ tests/

migrate:
	.venv/bin/python scripts/migrate.py

run:
	.venv/bin/uvicorn src.api.app:app --reload --port 8000
