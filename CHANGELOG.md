# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- **The remote MCP transport now requires the same bearer token.** The MCP
  library only offers OAuth resource-server auth — it rejects a token verifier
  unless handed an issuer URL and a resource server URL — so rather than invent
  an issuer and advertise discovery metadata for an authorization server that
  does not exist, the gate wraps the ASGI app instead (`mcp/auth.py`). The
  `mcp_remote` entrypoint now serves the transport through uvicorn to apply it.
  Verified end to end: no token gives 401, the right token completes an MCP
  initialize handshake.

- **Bearer authentication on the HTTP API** (roadmap item 07). `/ask` and
  `/tool` require `DA_API_TOKEN` when it is set, compared in constant time so a
  wrong token cannot be narrowed down by timing. `/health` stays open for probes
  but withholds backend detail from anonymous callers.
- Auth stays off by default so the offline quickstart needs no configuration, so
  the bind address carries the safety instead: `DA_API_HOST` now defaults to
  `127.0.0.1` (was `0.0.0.0`), and startup **refuses** a routable bind without a
  token unless `DA_ALLOW_UNAUTHENTICATED=true`. CI asserts the container refuses.
- The remote MCP transport binds loopback and refuses a routable bind without
  the same opt-in. It has **no** bearer auth: FastMCP's is an OAuth
  resource-server model, not a shared secret, and `DA_API_TOKEN` does not cover
  it. Said plainly in SECURITY.md rather than implied away.

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

- The MCP entrypoints were broken against current releases: `mcp` 2.0 removed
  `mcp.server.fastmcp`, which `mcp/server.py` imports, and the `mcp>=1.2`
  constraint resolved straight to it. Pinned to `>=1.9,<2` and verified, with a
  new CI job that installs the extra and builds the server — nothing previously
  imported it, which is why no job noticed.

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

- **Notion, Slack and Google Docs knowledge connectors** (roadmap items 03 and
  04), replacing the stubs that raised `NotImplementedError`. Each is opt-in per
  ingest run (`--notion`, `--slack`, `--gdocs`) and refuses to run without its
  credentials rather than contributing nothing silently.
  - Notion and Slack use `httpx` from core rather than their SDKs, so they add
    no dependency and their request handling is exercisable against mock
    transports. Google Docs needs `google-api-python-client` (new `gdocs`
    extra, imported lazily) because reaching Drive means a signed
    service-account assertion.
  - Slack is indexed per thread rather than per message, so a question is not
    separated from its answer.
  - Pagination is followed to the end and 429s are retried using the server's
    own `Retry-After`, capped so a bad header cannot stall an ingest.
  - **None of the three has been run against its live API.** The tests cover
    parsing, pagination, thread deduplication and rate limiting; they cannot
    cover whether the real APIs answer in the shapes assumed. Stated in the
    module docstrings, the README and the ingest CLI help.

- **Streaming responses** (roadmap item 02). `generate_stream` is now part of the
  provider surface, implemented for the mock, OpenAI-compatible, HF Inference and
  transformers backends; a provider without it still works, yielding the answer
  in one piece. `POST /ask/stream` emits Server-Sent Events — `delta` as text
  arrives, `step` when a tool runs, `done` with the full `/ask` body — and the UI
  renders tokens as they come.
- A tool-call turn is never streamed as text. Each turn is withheld only until
  its first non-whitespace character reveals prose or JSON, so the tool protocol
  cannot leak into the answer. Text withheld as a suspected call that turns out
  not to be one is released, so an answer starting with `{` is not lost.

- **Eval harness** (roadmap item 08). `evals/golden.json` holds 18 curated
  questions over `data/seed`, and `evals/run_eval.py` scores retrieval hit-rate
  and MRR, gating CI at 0.85 / 0.60. Retrieval is deterministic, so the floors
  catch a real regression instead of flapping — and a retrieval regression is
  otherwise invisible, since the agent keeps answering confidently from the
  wrong document. Answer groundedness is scored only with `--answers` against a
  real backend; the script refuses to score the `mock` provider rather than
  report a meaningless number.
- The seed corpus grew from one document to six. A single document made
  retrieval hit-rate trivially 1.0; the new documents share vocabulary
  deliberately, so retrieval has to discriminate.

- **Bounded tool-calling loop** (roadmap item 01). The orchestrator no longer
  answers in one shot: the model may request `knowledge_search`,
  `warehouse_query` or `list_dags` as a JSON object, the tool runs, and the
  result returns as an OBSERVATION for up to `DA_MAX_TOOL_STEPS` rounds before a
  final answer is forced. A model that asks for nothing just answers, which is
  the previous RAG path as the zero-tool case, and `DA_ENABLE_TOOLS=false`
  restores it explicitly. Failed calls — unknown tool, missing argument, SQL the
  guard rejects — come back as observations the model can correct, so a bad call
  never fails the request. `/ask` now returns the tool trace and
  `step_limit_reached`.
- `ToolSpec` replaces the `(callable, description)` tuple in the registry, so
  one definition drives the prompt catalogue, the `/tool` route and MCP.

- `httpx2` as a test dependency: starlette 1.6 deprecates driving `TestClient`
  with `httpx`, and the suite runs with `filterwarnings = error`.
- MIT `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue
  forms, a pull request template, and Dependabot configuration.
- Structured logging with request correlation (`observability.py`): an
  `X-Request-ID` accepted or minted at the edge, propagated through a context
  variable, and emitted as text or JSON via `DA_LOG_FORMAT`.
- GitHub Actions: lint/format/type checks, a test matrix over Python
  3.10–3.13 plus Windows and macOS, an end-to-end smoke job that exercises the
  documented offline path, a container job asserting the image runs non-root,
  a release workflow that refuses a tag disagreeing with the package version,
  and a CodeQL workflow that stays dormant while the repository is private
  (code scanning there needs GitHub Advanced Security) and enables itself
  if the repository is made public.
- FastAPI dependency injection for the runtime, so the app is testable without
  monkeypatching module globals.
- `make help`, `make check`, `make format`, `make types`, `make hooks`.

### Changed

- Ruff expanded from its default rules to 17 rule families (bugbear, bandit,
  pathlib, async, pytest-style and others), with `ruff format` enforced and
  pre-commit hooks including gitleaks.
- The test suite went from 5 tests at 62% coverage to 159 at 96%, with a 90%
  floor enforced in CI, split into focused modules with shared fixtures.
- The container is a multi-stage build running as an unprivileged user, with a
  healthcheck and OCI labels; `docker compose up` no longer requires a `.env`.
- `scripts/ingest.py` takes proper arguments via `argparse`, including
  `--append`.
- The package version has one source of truth instead of three.
