# Roadmap

What is worth doing next, and why. Items are ordered by value rather than by
ambition, and each says what "done" means so it can be closed rather than
drifting.

This is not a promise of dates. It is a record of what the project knows is
missing, kept honest enough that someone picking it up can tell the difference
between a feature that exists and one that merely compiles.

## Where it stands

The pieces are all present: one orchestrator behind five entrypoints, a bounded
tool-calling loop, streaming, a guarded warehouse adapter, bearer auth on both
the HTTP API and the remote MCP transport, an eval harness that gates CI, and a
knowledge base built offline from filesystem, Notion, Slack or Google Docs.

Two things temper that. Some of it has never run against the real thing, and
answer quality on the bundled corpus is measurably mediocre. Both are addressed
first below, because everything else is worth less until they are.

---

## 1. Verification debt

Code that exists but has never met its counterpart. This comes before new
features: building on an unverified base widens the surface that nobody has
checked.

### V1 — Run the SaaS connectors against real APIs

`knowledge/sources/{notion,slack,gdocs}.py` were written from the documented
APIs and are tested against mocks. Parsing, pagination, thread deduplication and
rate-limit handling are covered; **whether the real services answer in the
shapes assumed is not**. The most likely failure is a response field nested
differently from the assumption.

*Done when:* one `@pytest.mark.integration` test per connector reads a real
workspace with a read-only token and asserts a non-empty, correctly-attributed
`Document`. The marker already exists and is excluded from the default run, so
these can live in the suite without needing credentials in CI.

*Cost:* small. Most of the work is obtaining three read-only tokens.

### V2 — Parse the Airflow DAG with a real scheduler

`airflow/dags/data_agent_ingest.py` is checked structurally — one DAG, catchup
off, one active run, no module-scope import of the agent — but no scheduler has
ever loaded it.

*Done when:* a `DagBag` import test runs against a pinned Airflow version, or a
documented manual check records the Airflow version it was verified on.

*Cost:* small, but it pulls in Airflow, so it belongs in its own optional extra
and its own CI job rather than the default install.

---

## 2. Answer quality

The part a user actually feels. Today the eval harness reports **hit rate 0.889,
MRR 0.653** over 18 questions, with two cases failing on purpose to show where a
bag-of-words embedder gives up.

### Q1 — Measure `sentence_transformers` against the current baseline

The default `hashing` embedder cannot bridge a paraphrase. Switching backends is
one environment variable; whether it is worth the dependency is an open question
that the harness can answer.

*Done when:* `make eval` numbers for both backends are recorded in the README,
and the default is either changed or explicitly justified.

### Q2 — Grow the golden set past the point where one case moves the needle

Eighteen cases over six documents means a single regression shifts hit rate by
5.6%. The thresholds are correspondingly coarse.

*Done when:* the set covers enough questions that the CI floors can be raised
without becoming flaky, with the corpus grown alongside it so retrieval still
has to discriminate.

### Q3 — Score groundedness by something better than substring matching

`--answers` currently checks whether expected strings appear in the answer. That
catches a missing fact; it does not catch a fluent answer that cites the wrong
document, which is the failure mode retrieval-augmented systems actually have.

*Done when:* groundedness is scored by an LLM judge or by verifying that claims
trace to retrieved context, and the harness reports both.

### Q4 — Verify the citations the prompt asks for

The system prompt instructs the model to "cite sources by their `[source]` tag".
Nothing checks that it does, or that a cited tag was among the retrieved
contexts. A confidently mis-cited answer currently passes silently.

*Done when:* answers are parsed for `[source]` tags and any tag not in the
retrieved set is reported — as an eval metric first, and possibly as a runtime
warning.

---

## 3. Operations

### O1 — Reload the knowledge base without restarting

`Runtime` is `lru_cache`d and `Retriever` reads the store once at construction,
so a rebuild is invisible until the process restarts. That is documented, but it
makes scheduled ingestion awkward: the DAG rebuilds a store the running API
keeps ignoring.

*Done when:* an authenticated endpoint (or a file-mtime check on the request
path) picks up a rebuilt store, with a test asserting an ingest becomes visible
without a restart.

### O2 — Ingest incrementally

`ingest()` rebuilds from scratch, which is correct and cheap for a small corpus
and quadratic-feeling once it is not. The Qdrant backend already uses
deterministic point ids, so re-ingesting a chunk overwrites it — the groundwork
is there.

*Done when:* unchanged documents can be skipped by content hash, and a
deleted-source document is still removed rather than lingering.

### O3 — Rate limiting

There is none. `/ask` can drive a model backend and a warehouse query per
request, so an authenticated but careless client can be expensive.

*Done when:* a per-token request budget is enforced, returning 429 with
`Retry-After`.

### O4 — OpenTelemetry exporter

Structured logging with request correlation is in place; the optional tracing
exporter was deferred. Spans across entrypoint → orchestrator → model → tool
would make a slow answer explicable.

*Done when:* traces are exported behind an environment flag, off by default,
with the existing request id as the trace id.

---

## 4. Distribution

### D1 — Publish to PyPI

`release.yml` builds an sdist and a wheel, checks the metadata, verifies the tag
matches the package version — and then uploads them as a CI artifact. Nothing
installs `hf-data-agent` from anywhere.

*Done when:* a tagged release publishes to PyPI via a trusted publisher, so
`pip install hf-data-agent` works. This matters more than it sounds: the Airflow
DAG assumes workers can install the package.

### D2 — Publish the container image

The image builds and is smoke-tested in CI on every push, then discarded.

*Done when:* tagged releases push to GHCR, tagged with both the version and
`latest`.

---

## 5. Maintenance

### M1 — Migrate to `mcp` 2.0

`mcp` is pinned `>=1.9,<2` because 2.0 removed `mcp.server.fastmcp`, which
`mcp/server.py` is built on. The pin is a hold, not a decision, and Dependabot
will keep proposing the upgrade.

The shape of the migration is known: `FastMCP` becomes `MCPServer`, the `@tool`
decorator survives, and `host`/`port` move from the constructor into `run()`.
Note that 2.0 does **not** change the auth picture — its `token_verifier` still
requires OAuth `AuthSettings`, so the ASGI bearer gate in `mcp/auth.py` stays
either way.

*Done when:* the pin is removed, the `mcp-extra` CI job builds the server on
2.x, and the bearer gate still rejects an anonymous request.

---

## 6. Capability

Deliberately last. These are the interesting ideas, and they are worth less than
the unglamorous items above until those are done.

### C1 — Multi-turn conversations

`answer(question)` takes a question and no history, so every request starts
cold. A follow-up like "and by region?" cannot work.

*Done when:* a conversation id carries prior turns into the prompt, with a bound
on how much history is replayed and a documented retention policy — transcripts
of questions about company data are not neutral to keep.

### C2 — Run independent tool calls in parallel

The loop executes one tool per round. Two independent lookups therefore cost two
model round-trips.

*Done when:* a turn may request several tools and they execute concurrently,
without changing the single-tool path or the step budget's meaning.

---

## Non-goals

Saying what this will not become is as useful as the list above.

- **A general agent framework.** The orchestrator is deliberately small and
  readable. It is not trying to compete with LangChain or LlamaIndex, and
  adopting one of them would remove the property that makes this legible.
- **Writing to the warehouse.** The SQL guard rejects anything that is not a
  single read-only statement, and the intended deployment is a database role
  holding `SELECT` and nothing else. An agent that can write is a different
  project with a different risk profile.
- **Multi-tenancy.** One token, one knowledge base, one warehouse role. Serving
  several tenants from one process would touch retrieval, auth and logging at
  once, and is better solved by running several instances.
- **A model of its own.** The point is that the model is swappable. Anything
  that assumes a particular model's quirks belongs behind `ModelProvider`.

---

## Contributing to this list

An item earns a place by naming a concrete gap and what would close it. If you
cannot say what "done" looks like, it is an idea rather than a roadmap entry —
open an issue and discuss it there first. See [CONTRIBUTING.md](CONTRIBUTING.md).
