"""Settings parsing, especially the values that gate the SQL guard."""

from __future__ import annotations

import pytest

from data_agent.config import Settings, get_settings


class TestDefaults:
    def test_defaults_run_offline(self):
        settings = Settings()
        assert settings.model_backend == "mock"
        assert settings.embedder_backend == "hashing"
        assert settings.warehouse_dsn.startswith("sqlite://")

    def test_get_settings_is_cached(self):
        assert get_settings() is get_settings()

    def test_an_invalid_backend_is_rejected(self):
        with pytest.raises(ValueError, match="model_backend"):
            Settings(model_backend="telepathy")


class TestAllowedTables:
    def test_empty_means_unrestricted(self):
        assert Settings(warehouse_allowed_tables="").allowed_tables is None

    def test_whitespace_only_means_unrestricted(self):
        assert Settings(warehouse_allowed_tables="  ,  , ").allowed_tables is None

    def test_names_are_split_and_lowercased(self):
        settings = Settings(warehouse_allowed_tables="Revenue, ORDERS")
        assert settings.allowed_tables == frozenset({"revenue", "orders"})

    def test_surrounding_whitespace_is_trimmed(self):
        settings = Settings(warehouse_allowed_tables="  revenue  ,orders  ")
        assert settings.allowed_tables == frozenset({"revenue", "orders"})


class TestEnvironmentBinding:
    def test_the_da_prefix_is_honoured(self, monkeypatch):
        monkeypatch.setenv("DA_RETRIEVAL_TOP_K", "9")
        assert Settings().retrieval_top_k == 9

    def test_unprefixed_variables_are_ignored(self, monkeypatch):
        monkeypatch.setenv("RETRIEVAL_TOP_K", "9")
        assert Settings().retrieval_top_k == 4
