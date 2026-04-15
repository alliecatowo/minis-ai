"""Tests for plugin registry and loader.

Covers:
- PluginRegistry: register/get/list sources and clients
- PluginRegistry: overwrite warning
- PluginRegistry: KeyError on missing source/client
- load_plugins(): all built-in sources registered
- IngestionResult dataclass construction
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.plugins.base import ClientPlugin, IngestionResult, IngestionSource
from app.plugins.registry import PluginRegistry


# ---------------------------------------------------------------------------
# Helpers — minimal concrete implementations
# ---------------------------------------------------------------------------


class _FakeSource(IngestionSource):
    """Minimal concrete IngestionSource for testing."""

    def __init__(self, name: str = "fake_source"):
        self.name = name
        self.source_type = "voice"

    async def fetch(self, identifier: str, **config):
        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence="fake evidence",
        )


class _FakeClient(ClientPlugin):
    """Minimal concrete ClientPlugin for testing."""

    def __init__(self, name: str = "fake_client"):
        self.name = name

    async def setup(self, app) -> None:
        pass


# ---------------------------------------------------------------------------
# IngestionResult
# ---------------------------------------------------------------------------


class TestIngestionResult:
    def test_basic_construction(self):
        result = IngestionResult(
            source_name="github",
            identifier="torvalds",
            evidence="some evidence text",
        )
        assert result.source_name == "github"
        assert result.identifier == "torvalds"
        assert result.evidence == "some evidence text"

    def test_defaults_for_raw_data_and_stats(self):
        result = IngestionResult(
            source_name="github",
            identifier="user",
            evidence="evidence",
        )
        assert result.raw_data == {}
        assert result.stats == {}

    def test_with_raw_data(self):
        result = IngestionResult(
            source_name="github",
            identifier="user",
            evidence="evidence",
            raw_data={"commits": 42},
            stats={"repos": 10},
        )
        assert result.raw_data["commits"] == 42
        assert result.stats["repos"] == 10


# ---------------------------------------------------------------------------
# PluginRegistry — sources
# ---------------------------------------------------------------------------


class TestPluginRegistrySources:
    def setup_method(self):
        self.registry = PluginRegistry()

    def test_register_source(self):
        source = _FakeSource("test_source")
        self.registry.register_source(source)
        assert "test_source" in self.registry.list_sources()

    def test_get_registered_source(self):
        source = _FakeSource("my_source")
        self.registry.register_source(source)
        retrieved = self.registry.get_source("my_source")
        assert retrieved is source

    def test_get_missing_source_raises_key_error(self):
        with pytest.raises(KeyError):
            self.registry.get_source("nonexistent_source")

    def test_list_sources_empty_initially(self):
        assert self.registry.list_sources() == []

    def test_list_sources_after_registration(self):
        self.registry.register_source(_FakeSource("s1"))
        self.registry.register_source(_FakeSource("s2"))
        sources = self.registry.list_sources()
        assert "s1" in sources
        assert "s2" in sources
        assert len(sources) == 2

    def test_overwriting_source_replaces_it(self):
        source1 = _FakeSource("dup")
        source2 = _FakeSource("dup")
        self.registry.register_source(source1)
        self.registry.register_source(source2)
        assert self.registry.get_source("dup") is source2

    def test_overwriting_source_logs_warning(self, caplog):
        source1 = _FakeSource("dup_warn")
        source2 = _FakeSource("dup_warn")
        self.registry.register_source(source1)
        with caplog.at_level(logging.WARNING, logger="app.plugins.registry"):
            self.registry.register_source(source2)
        assert any("dup_warn" in r.message for r in caplog.records)

    def test_register_multiple_different_sources(self):
        for i in range(5):
            self.registry.register_source(_FakeSource(f"source_{i}"))
        assert len(self.registry.list_sources()) == 5


# ---------------------------------------------------------------------------
# PluginRegistry — clients
# ---------------------------------------------------------------------------


class TestPluginRegistryClients:
    def setup_method(self):
        self.registry = PluginRegistry()

    def test_register_client(self):
        client = _FakeClient("web")
        self.registry.register_client(client)
        assert "web" in self.registry.list_clients()

    def test_get_registered_client(self):
        client = _FakeClient("my_client")
        self.registry.register_client(client)
        retrieved = self.registry.get_client("my_client")
        assert retrieved is client

    def test_get_missing_client_raises_key_error(self):
        with pytest.raises(KeyError):
            self.registry.get_client("missing_client")

    def test_list_clients_empty_initially(self):
        assert self.registry.list_clients() == []

    def test_overwriting_client_replaces_it(self):
        c1 = _FakeClient("dup_client")
        c2 = _FakeClient("dup_client")
        self.registry.register_client(c1)
        self.registry.register_client(c2)
        assert self.registry.get_client("dup_client") is c2

    def test_overwriting_client_logs_warning(self, caplog):
        c1 = _FakeClient("dup_client_warn")
        c2 = _FakeClient("dup_client_warn")
        self.registry.register_client(c1)
        with caplog.at_level(logging.WARNING, logger="app.plugins.registry"):
            self.registry.register_client(c2)
        assert any("dup_client_warn" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# PluginRegistry — setup_clients
# ---------------------------------------------------------------------------


class TestSetupClients:
    @pytest.mark.asyncio
    async def test_setup_clients_calls_setup_on_all_clients(self):
        registry = PluginRegistry()
        mock_app = MagicMock()

        client1 = MagicMock()
        client1.name = "c1"
        client1.setup = AsyncMock()

        client2 = MagicMock()
        client2.name = "c2"
        client2.setup = AsyncMock()

        registry.register_client(client1)
        registry.register_client(client2)
        await registry.setup_clients(mock_app)

        client1.setup.assert_awaited_once_with(mock_app)
        client2.setup.assert_awaited_once_with(mock_app)

    @pytest.mark.asyncio
    async def test_setup_clients_empty_registry_no_error(self):
        registry = PluginRegistry()
        await registry.setup_clients(MagicMock())  # Should not raise


# ---------------------------------------------------------------------------
# load_plugins() — built-in registrations
# ---------------------------------------------------------------------------


EXPECTED_SOURCES = [
    "github",
    "claude_code",
    "blog",
    "stackoverflow",
    "devblog",
    "hackernews",
    "website",
]


class TestLoadPlugins:
    def setup_method(self):
        """Use a fresh registry to avoid polluting the global singleton."""
        from app.plugins.registry import registry
        self._original_sources = dict(registry._sources)
        self._original_clients = dict(registry._clients)

    def teardown_method(self):
        """Restore global registry."""
        from app.plugins.registry import registry
        registry._sources = self._original_sources
        registry._clients = self._original_clients

    def test_load_plugins_registers_all_sources(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import registry

        # Clear and reload
        registry._sources.clear()
        registry._clients.clear()
        load_plugins()

        registered = registry.list_sources()
        for name in EXPECTED_SOURCES:
            assert name in registered, f"Source '{name}' not registered after load_plugins()"

    def test_load_plugins_registers_web_client(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import registry

        registry._sources.clear()
        registry._clients.clear()
        load_plugins()

        assert "web" in registry.list_clients()

    def test_source_instances_are_ingestion_sources(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import registry

        registry._sources.clear()
        registry._clients.clear()
        load_plugins()

        for name in EXPECTED_SOURCES:
            source = registry.get_source(name)
            assert isinstance(source, IngestionSource), (
                f"Source '{name}' is not an IngestionSource instance"
            )

    def test_source_name_attribute_matches_registration_key(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import registry

        registry._sources.clear()
        registry._clients.clear()
        load_plugins()

        for name in EXPECTED_SOURCES:
            source = registry.get_source(name)
            assert source.name == name, (
                f"Source.name '{source.name}' does not match registry key '{name}'"
            )
