"""Central configuration. Everything is driven by env vars (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ModelBackend = Literal["mock", "transformers", "openai_compatible", "hf_inference"]
EmbedderBackend = Literal["hashing", "sentence_transformers"]
LogFormat = Literal["text", "json"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DA_", env_file=".env", extra="ignore")

    # ---- Model (the "MODEL / GPT-5.2" box, now an open HF model) ----
    model_backend: ModelBackend = "mock"
    # Any instruct model on the Hub works. Sensible open defaults:
    #   Qwen/Qwen2.5-7B-Instruct        (strong, needs a GPU)
    #   Qwen/Qwen2.5-1.5B-Instruct      (runs on CPU/small GPU)
    #   meta-llama/Llama-3.2-3B-Instruct
    #   microsoft/Phi-4-mini-instruct
    model_id: str = "Qwen/Qwen2.5-1.5B-Instruct"
    model_max_new_tokens: int = 512
    model_temperature: float = 0.2
    # For openai_compatible (vLLM / TGI) backends:
    model_base_url: str = "http://localhost:8001/v1"
    model_api_key: str = "not-needed"
    # For hf_inference backend:
    hf_token: str = ""

    # ---- Knowledge base / RAG (pre-processed offline) ----
    embedder_backend: EmbedderBackend = "hashing"
    embedder_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384
    vector_store_path: str = "data/vector_store.json"
    retrieval_top_k: int = 4

    # ---- Tool-calling loop ----
    #: False restores the original single-shot RAG behaviour.
    enable_tools: bool = True
    #: Maximum tool executions per question, before a final answer is forced.
    max_tool_steps: int = 4
    #: Observations longer than this are truncated before going back to the model.
    tool_result_max_chars: int = 4000

    # ---- Data platform (online sync calls) ----
    # Use a database user holding SELECT and nothing else: the SQL guard is a
    # safety net, the grant is the boundary. See SECURITY.md.
    warehouse_dsn: str = "sqlite:///data/warehouse.db"
    #: Row cap applied to every warehouse query.
    warehouse_max_rows: int = 1000
    #: Comma-separated table allow-list. Empty means "no table restriction".
    warehouse_allowed_tables: str = ""
    airflow_base_url: str = "http://localhost:8080"
    spark_master: str = "local[*]"

    # ---- API ----
    #: Loopback by default: /ask and /tool can reach the warehouse, so the
    #: server must be asked to expose them rather than doing it silently.
    #: Containers set 0.0.0.0 explicitly and supply a token.
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    #: Bearer token required by /ask and /tool. Empty disables authentication,
    #: which is only permitted on a loopback binding — see api/security.py.
    api_token: str = ""
    #: Escape hatch for a port already protected by a proxy or private network.
    allow_unauthenticated: bool = False

    # ---- Remote MCP entrypoint ----
    #: Loopback by default. The MCP transport carries no bearer auth of its
    #: own (see api/security.require_safe_mcp_binding), so exposing it is
    #: an explicit decision.
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8001

    #: Root log level for every entrypoint.
    log_level: str = "INFO"
    #: "text" for humans, "json" for log shipping.
    log_format: LogFormat = "text"

    # ---- Slack entrypoint ----
    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    @property
    def allowed_tables(self) -> frozenset[str] | None:
        """Parsed `warehouse_allowed_tables`, or None when unrestricted."""
        names = {n.strip().lower() for n in self.warehouse_allowed_tables.split(",")}
        names.discard("")
        return frozenset(names) or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
