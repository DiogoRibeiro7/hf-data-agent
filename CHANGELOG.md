# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- `warehouse_query` no longer executes destructive SQL. It was documented as
  read-only but ran whatever it was given: a `DROP TABLE` sent to `POST /tool`
  removed the table and then surfaced as a confusing `ResourceClosedError`. A
  new `datasources.sql_guard` validates every statement before it reaches the
  engine — one statement only, `SELECT`/`WITH` heads only, and no destructive
  verb anywhere, which also blocks data-modifying CTEs and comment-hidden
  payloads. Rejections now return `400`, not `500`.
- Added `DA_WAREHOUSE_MAX_ROWS` (row cap, with truncation disclosed in the
  result) and `DA_WAREHOUSE_ALLOWED_TABLES` (optional table allow-list).
- The agent UI renders answers and knowledge-base source names as text rather
  than assigning `innerHTML`. Source names come from ingested documents, so
  markup in a filename previously reached every viewer's browser.
- Documented the real threat model in `SECURITY.md`, including that the API and
  MCP transports ship unauthenticated and that the SQL guard is a safety net,
  not a substitute for a read-only database grant.

### Fixed

- Ingestion is idempotent. `VectorStore` loads any existing store on
  construction and `ingest()` then appended to it, so each `make ingest` added a
  second copy of every chunk and the duplicates crowded out genuine matches.
  Saves are now atomic (temporary file plus replace).
- Cosine search rejects a dimension mismatch instead of scoring a prefix. A
  384-dimensional query scored `1.0` against an unrelated 768-dimensional
  vector, so switching embedder backends without re-ingesting returned
  confident nonsense.
- `MockProvider` reports grounding correctly. It matched the substring
  `"CONTEXT"`, which the base system prompt itself contains, so every
  ungrounded answer claimed context had been provided — visible to anyone
  running the default backend.
- The request-id context variable is reset after the access log line is
  emitted, so the one record summarising each request is no longer the only one
  missing its id.
- `Runtime` exposes `close()` / `aclose()`, called from a FastAPI lifespan, so
  connection pools and HTTP clients are released rather than leaked.
- `mypy --strict` passes: several `Any` values leaked across the `resp.json()`,
  `.tolist()` and `tokenizer.decode()` boundaries, and the `TOOLS` registry was
  inferred from its first entry, which type-checked `/tool` dispatch against the
  wrong signature.

### Added

- MIT `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue
  forms, a pull request template, and Dependabot configuration.
- Structured logging with request correlation (`observability.py`): an
  `X-Request-ID` accepted or minted at the edge, propagated through a context
  variable, and emitted as text or JSON via `DA_LOG_FORMAT`.
- GitHub Actions: lint/format/type checks, a test matrix over Python
  3.10–3.13 plus Windows and macOS, an end-to-end smoke job that exercises the
  documented offline path, a container job asserting the image runs non-root,
  CodeQL analysis, and a release workflow that refuses a tag disagreeing with
  the package version.
- FastAPI dependency injection for the runtime, so the app is testable without
  monkeypatching module globals.
- `make help`, `make check`, `make format`, `make types`, `make hooks`.

### Changed

- Ruff expanded from its default rules to 17 rule families (bugbear, bandit,
  pathlib, async, pytest-style and others), with `ruff format` enforced and
  pre-commit hooks including gitleaks.
- The test suite went from 5 tests at 62% coverage to 158 at 96%, with a 90%
  floor enforced in CI, split into focused modules with shared fixtures.
- The container is a multi-stage build running as an unprivileged user, with a
  healthcheck and OCI labels; `docker compose up` no longer requires a `.env`.
- `scripts/ingest.py` takes proper arguments via `argparse`, including
  `--append`.
- The package version has one source of truth instead of three.
