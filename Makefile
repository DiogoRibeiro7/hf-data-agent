.PHONY: install seed ingest api mcp-local mcp-remote slack test lint

install:
	pip install -e ".[dev]"

seed:
	python scripts/seed_warehouse.py

ingest:
	python scripts/ingest.py data/seed

api:
	python -m data_agent.entrypoints.run_api

mcp-local:
	python -m data_agent.entrypoints.mcp_local

mcp-remote:
	python -m data_agent.entrypoints.mcp_remote

slack:
	python -m data_agent.entrypoints.slack_app

test:
	pytest -q

lint:
	ruff check src tests
