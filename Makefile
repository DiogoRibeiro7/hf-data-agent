.PHONY: help install hooks seed ingest api mcp-local mcp-remote slack \
        test lint format format-check types check clean docker-build docker-run

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "\033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup ----
install:  ## Editable install with dev extras
	pip install -e ".[dev]"

hooks:  ## Install the pre-commit git hooks
	pre-commit install

seed:  ## Create the local SQLite warehouse
	python scripts/seed_warehouse.py

ingest:  ## Rebuild the RAG vector store from data/seed
	python scripts/ingest.py data/seed

# ----------------------------------------------------------- entrypoints ----
api:  ## Agent UI + HTTP API on $DA_API_PORT (default 8000)
	python -m data_agent.entrypoints.run_api

mcp-local:  ## LOCAL MCP server over stdio (needs ".[mcp]")
	python -m data_agent.entrypoints.mcp_local

mcp-remote:  ## REMOTE MCP server over HTTP (needs ".[mcp]")
	python -m data_agent.entrypoints.mcp_remote

slack:  ## Slack bot (needs ".[slack]")
	python -m data_agent.entrypoints.slack_app

# ---------------------------------------------------------------- checks ----
test:  ## Run the test suite with coverage
	pytest

lint:  ## Lint with ruff
	ruff check src tests scripts

format:  ## Format with ruff
	ruff format src tests scripts

format-check:  ## Verify formatting without writing
	ruff format --check src tests scripts

types:  ## Type-check with mypy
	mypy src

check: lint format-check types test  ## Everything CI runs

# ---------------------------------------------------------------- docker ----
docker-build:  ## Build the container image
	docker build -t hf-data-agent:local .

docker-run:  ## Run the container against the offline defaults
	docker run --rm -p 8000:8000 -e DA_MODEL_BACKEND=mock hf-data-agent:local

# ----------------------------------------------------------------- misc -----
clean:  ## Remove caches and generated artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache .benchmarks htmlcov \
	       .coverage coverage.xml dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
