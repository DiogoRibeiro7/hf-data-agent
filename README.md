# hf-data-agent

An internal **data agent** with the architecture from the reference diagram —
but the proprietary model is replaced by an **open-source LLM from Hugging Face**.

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

## Quickstart (runs with zero downloads — `mock` model + `hashing` embeddings)

```bash
make install
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

## Plug in a real open model

| backend             | how                                                            |
|---------------------|---------------------------------------------------------------|
| `transformers`      | `pip install ".[transformers]"`, set `DA_MODEL_ID` (local)    |
| `openai_compatible` | serve with vLLM/TGI (`scripts/serve_model.sh`), point base_url |
| `hf_inference`      | set `DA_HF_TOKEN` + `DA_MODEL_ID` (hosted, no infra)          |

Any instruct model works: `Qwen/Qwen2.5-7B-Instruct`, `meta-llama/Llama-3.2-3B-Instruct`,
`microsoft/Phi-4-mini-instruct`, `mistralai/Mistral-7B-Instruct-*`.

## Entrypoints

```bash
make api          # Agent UI + HTTP API
make mcp-local    # LOCAL  MCP (stdio)   — needs ".[mcp]"
make mcp-remote   # REMOTE MCP (http)    — needs ".[mcp]"
make slack        # Slack bot            — needs ".[slack]"
```

## Layout

```
src/data_agent/
  config.py            env-driven settings
  runtime.py           single wiring point (model + retriever + datasources)
  orchestrator/        RAG core (the AGENT-API brain)
  model/               provider abstraction: mock | transformers | vLLM/TGI | HF Inference
  knowledge/           RAG: embedder, store, sources, offline ingest, online retrieve
  datasources/         live adapters: warehouse (works), spark/airflow/metadata
  mcp/                 MCP server + shared tool definitions
  entrypoints/         ui / api / mcp_local / mcp_remote / slack
```
