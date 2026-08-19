"""Single wiring point. Builds the model, retriever, and data sources from
settings and holds them. Both the HTTP API and the MCP servers share one Runtime
so 'tools' behave identically however they're reached."""
from __future__ import annotations

from functools import lru_cache

from data_agent.config import Settings, get_settings
from data_agent.datasources.base import DataSource
from data_agent.datasources.platform import AirflowSource
from data_agent.datasources.warehouse import WarehouseSource
from data_agent.knowledge.retriever import Retriever
from data_agent.model.base import ModelProvider, build_provider


class Runtime:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.model: ModelProvider = build_provider(self.settings)
        self.retriever = Retriever(self.settings)
        self.datasources: dict[str, DataSource] = {
            "warehouse": WarehouseSource(self.settings.warehouse_dsn),
            "airflow": AirflowSource(self.settings.airflow_base_url),
            # spark / metadata are stubs — add when implemented.
        }


@lru_cache
def get_runtime() -> Runtime:
    return Runtime()
