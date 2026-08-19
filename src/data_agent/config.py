"""Central configuration. Everything is driven by env vars (see .env.example)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ModelBackend = Literal["mock", "transformers", "openai_compatible", "hf_inference"]
EmbedderBackend = Literal["hashing", "sentence_transformers"]


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

    # ---- Data platform (online sync calls) ----
    warehouse_dsn: str = "sqlite:///data/warehouse.db"
    airflow_base_url: str = "http://localhost:8080"
    spark_master: str = "local[*]"

    # ---- API ----
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ---- Slack entrypoint ----
    slack_bot_token: str = ""
    slack_signing_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
