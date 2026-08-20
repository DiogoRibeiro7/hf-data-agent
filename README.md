# hf-data-agent

[![CI](https://github.com/DiogoRibeiro7/hf-data-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/DiogoRibeiro7/hf-data-agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![mypy](https://img.shields.io/badge/mypy-strict-2a6db2)](pyproject.toml)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230)](https://github.com/astral-sh/ruff)

An internal **data agent**: several entrypoints funnel into one Agent API, which
grounds an **open-source LLM from Hugging Face** in your company knowledge base
and lets it pull fresh numbers from your data platform.

```
  ENTRYPOINTS                 AGENT-API                 MODEL
  ┌───────────────┐                                ┌──────────────────┐
  │ Agent UI      │─┐                            ┌▶│ open HF model     │
  │ Local MCP     │ │      ┌──────────────┐  MCP │ │ (Qwen/Llama/Phi…) │
  │ Remote MCP    │ ├─────▶│ Orchestrator │◀─────┘ └──────────────────┘
  │ Slack         │─┘      │  (RAG core)  │
  └───────────────┘        └──────┬───────┘
                       offline ▲  │  ▼ online sync
              ┌─────────────────┘  └─────────────────┐
   ┌──────────────────────┐            ┌──────────────────────────┐
   │ Knowledge base (RAG) │            │ Data platform            │
   │ fs / Notion / GDocs  │            │ warehouse / Airflow /    │
   │ / Slack  (pre-built) │            │ Spark / metadata (live)  │
   └──────────────────────┘            └──────────────────────────┘
```

## Quickstart

The defaults run with **zero downloads and no network**: a deterministic `mock`
model, a dependency-free `hashing` embedder, and a local SQLite warehouse.

```bash
make install      # editable install with dev extras
make seed         # tiny SQLite warehouse
make ingest       # build the RAG store from data/seed
make api          # http://localhost:8000  (UI + /ask + /tool)
```

```bash
curl -s localhost:8000/ask -H 'content-type: application/json' \
  -d '{"question":"How is the daily_revenue DAG scheduled?"}'

curl -s localhost:8000/tool -H 'content-type: application/json' \
  -d '{"name":"warehouse_query","args":{"sql":"select region, sum(revenue_usd) from revenue group by region"}}'
```

> The knowledge base is read into memory when the process starts. After a
> `make ingest`, restart the API for the new chunks to become visible — that is
> the offline/online split working as designed, not a bug.

## Security

Read [SECURITY.md](SECURITY.md) before exposing this beyond localhost. In short:

- **The API and the MCP transports are unauthenticated**, and `DA_API_HOST`
  defaults to `0.0.0.0`. Put an authenticating proxy in front of them.
- **`warehouse_query` is guarded, not sandboxed.** Every statement must be a
  single read-only query; destructive verbs, stacked statements and
  data-modifying CTEs are rejected. Even so, point `DA_WAREHOUSE_DSN` at a
  database user holding `SELECT` and nothing else — the grant is the boundary,
  the guard is a safety net.
- **Ingested content reaches the model**, so treat every knowledge source as
  semi-trusted: prompt injection in a document can attempt to steer tool calls.

## Plug in a real open model

| backend             | how                                                            |
|---------------------|----------------------------------------------------------------|
| `mock`              | default; deterministic, offline, no dependencies               |
| `transformers`      | `pip install ".[transformers]"`, set `DA_MODEL_ID` (local)     |
| `openai_compatible` | serve with vLLM/TGI (`scripts/serve_model.sh`), point base_url |
| `hf_inference`      | set `DA_HF_TOKEN` + `DA_MODEL_ID` (hosted, no infra)           |

Any instruct model works: `Qwen/Qwen2.5-7B-Instruct`,
`meta-llama/Llama-3.2-3B-Instruct`, `microsoft/Phi-4-mini-instruct`,
`mistralai/Mistral-7B-Instruct-*`.

## Entrypoints

```bash
make api          # Agent UI + HTTP API
make mcp-local    # LOCAL  MCP (stdio)   — needs ".[mcp]"
make mcp-remote   # REMOTE MCP (http)    — needs ".[mcp]"
make slack        # Slack bot            — needs ".[slack]"
```

All of them reach the same `Orchestrator`, so a question asked in Slack and the
same question asked over MCP take an identical path.

### HTTP API

| method | path      | purpose                                              |
|--------|-----------|------------------------------------------------------|
| `GET`  | `/`       | Agent UI                                             |
| `GET`  | `/health` | status, version, active backend, knowledge-base size |
| `POST` | `/ask`    | RAG answer, with the retrieved contexts              |
| `POST` | `/tool`   | invoke one tool directly                             |

Every response carries an `X-Request-ID`; send your own header to correlate
with upstream logs.

## Configuration

Every setting is an environment variable prefixed `DA_`; see
[.env.example](.env.example) for the full list.

| variable                         | default                       | purpose                              |
|----------------------------------|-------------------------------|--------------------------------------|
| `DA_MODEL_BACKEND`               | `mock`                        | which provider to build              |
| `DA_MODEL_ID`                    | `Qwen/Qwen2.5-1.5B-Instruct`  | model to load or request             |
| `DA_EMBEDDER_BACKEND`            | `hashing`                     | `hashing` or `sentence_transformers` |
| `DA_VECTOR_STORE_PATH`           | `data/vector_store.json`      | where ingestion writes               |
| `DA_RETRIEVAL_TOP_K`             | `4`                           | chunks injected into the prompt      |
| `DA_WAREHOUSE_DSN`               | `sqlite:///data/warehouse.db` | use a read-only database user        |
| `DA_WAREHOUSE_MAX_ROWS`          | `1000`                        | row cap per query                    |
| `DA_WAREHOUSE_ALLOWED_TABLES`    | *(empty)*                     | optional table allow-list            |
| `DA_LOG_LEVEL` / `DA_LOG_FORMAT` | `INFO` / `text`               | `json` emits one object per line     |

Changing `DA_EMBEDDER_BACKEND` or `DA_EMBEDDER_MODEL` changes the embedding
width, so re-run `make ingest` afterwards. Querying a store built by a
different embedder is refused rather than silently scored against vectors of
the wrong shape.

## Docker

```bash
docker build -t hf-data-agent .
docker run --rm -p 8000:8000 -e DA_MODEL_BACKEND=mock hf-data-agent
```

The image is multi-stage and runs as an unprivileged user. `docker compose up`
additionally starts vLLM serving an open model behind an OpenAI-compatible
endpoint (needs a GPU; drop that service otherwise).

## Layout

```
src/data_agent/
  config.py            env-driven settings
  observability.py     logging setup + request correlation
  runtime.py           single wiring point (model + retriever + datasources)
  orchestrator/        RAG core (the AGENT-API brain)
  model/               provider abstraction: mock | transformers | vLLM/TGI | HF Inference
  knowledge/           RAG: embedder, store, sources, offline ingest, online retrieve
  datasources/         live adapters: warehouse (guarded), spark/airflow/metadata
  mcp/                 MCP server + shared tool definitions
  entrypoints/         ui / api / mcp_local / mcp_remote / slack
```

## Development

```bash
make install && make hooks
make check        # lint, format, types, tests — exactly what CI runs
```

`make help` lists every target. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
architecture invariants a change has to preserve.

## License

[MIT](LICENSE)
