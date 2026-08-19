# Contributing

Thanks for taking the time to contribute. This document covers the local setup,
the checks a change has to pass, and the architectural rules that keep the
codebase coherent.

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install          # editable install with dev extras
make hooks            # install the pre-commit hooks (recommended)
make seed ingest      # build the local SQLite warehouse + vector store
make test
```

The defaults are deliberately offline: the `mock` model provider, the `hashing`
embedder, and a SQLite warehouse. You can run the entire stack and the whole test
suite with no GPU, no API token, and no model download.

## Definition of done

Every change must satisfy all of the following before review:

| Check          | Command       | Notes                                          |
|----------------|---------------|------------------------------------------------|
| Tests          | `make test`   | Coverage must not regress below the configured floor |
| Lint           | `make lint`   | `ruff check` — no warnings                     |
| Format         | `make format` | `ruff format` — no diff                        |
| Types          | `make types`  | `mypy src`                                     |
| Everything     | `make check`  | Runs all of the above, same as CI              |

Additionally:

- The offline default path must still work end to end
  (`make seed ingest` then `make api` and a `POST /ask`).
- A new model backend must be documented in both `.env.example` and the backend
  table in the README.
- A new tool must be added to `mcp/tools.py` only — both the HTTP `/tool` route
  and the MCP server derive their tool list from there.

## Architecture invariants

These are load-bearing. A change that breaks one of them needs an explicit
discussion in the pull request, not a quiet workaround.

- **One funnel.** Every entrypoint (`ui`, `api`, `mcp_local`, `mcp_remote`,
  `slack`) reaches the same `Orchestrator`. An entrypoint never talks to the
  model or a datasource directly.
- **The model sits behind `ModelProvider`.** The orchestrator only calls
  `provider.generate(messages)`. A new backend is a new module in `model/` plus
  one branch in `model.base.build_provider`; nothing else changes.
- **Knowledge is offline, data is online.** The RAG store is built by
  `scripts/ingest.py` and is only *read* on the request path. Warehouse, Airflow
  and Spark are queried live and exposed as tools. Do not blur the two.
- **Tools are defined once**, in `mcp/tools.py`.
- **Heavy dependencies are imported lazily** inside functions (torch,
  transformers, sentence-transformers, mcp, slack_bolt) so the core stays
  installable and tests never trigger a model download.

## Code style

- Python ≥ 3.10, type hints throughout, `from __future__ import annotations` at
  the top of every module.
- Formatting and import order are handled by `ruff format` and `ruff check --fix`;
  do not hand-tune them.
- Keep modules small and single-purpose. No speculative abstraction.

## Commits and pull requests

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`, `perf:`.
- One logical change per pull request. Include the reasoning, not just the
  diff — say what breaks if the change is wrong.
- Update `CHANGELOG.md` under `## [Unreleased]` for anything user-visible.

## Reporting security issues

Do not open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).
