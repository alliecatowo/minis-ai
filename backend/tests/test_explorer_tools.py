"""Tests for build_explorer_tools() — the DB-backed explorer tool suite.

Covers:
- build_explorer_tools() returns exactly 12 tools
- Each tool has a non-empty name, description, and valid parameters schema
- Parameters schemas are JSON Schema objects with 'type' and 'properties' keys
- 'required' fields list only valid property names
- Tool handlers are async callables
- DB interaction is fully mocked — no real DB required
"""

from __future__ import annotations

import asyncio
import inspect
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.agent import AgentTool
from app.synthesis.explorers.tools import build_explorer_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session():
    """Fully mocked SQLAlchemy async session."""
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def tools(mock_session):
    """Build the explorer tool suite with a mocked session."""
    return build_explorer_tools(
        mini_id="test-mini-id",
        source_type="github",
        db_session=mock_session,
    )


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


EXPECTED_TOOL_NAMES = {
    "browse_evidence",
    "search_evidence",
    "read_item",
    "save_finding",
    "save_memory",
    "save_quote",
    "save_knowledge_node",
    "save_knowledge_edge",
    "save_principle",
    "mark_explored",
    "get_progress",
    "finish",
}


class TestBuildExplorerToolsStructure:
    def test_returns_list(self, tools):
        assert isinstance(tools, list)

    def test_returns_12_tools(self, tools):
        assert len(tools) == 12

    def test_all_tools_are_agent_tool_instances(self, tools):
        for tool in tools:
            assert isinstance(tool, AgentTool), f"{tool} is not an AgentTool"

    def test_tool_names_are_correct(self, tools):
        names = {t.name for t in tools}
        assert names == EXPECTED_TOOL_NAMES

    def test_no_duplicate_names(self, tools):
        names = [t.name for t in tools]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Descriptions
# ---------------------------------------------------------------------------


class TestToolDescriptions:
    def test_all_tools_have_non_empty_description(self, tools):
        for tool in tools:
            assert tool.description, f"Tool '{tool.name}' has empty description"
            assert len(tool.description) > 10, (
                f"Tool '{tool.name}' description too short: {tool.description!r}"
            )

    def test_descriptions_are_strings(self, tools):
        for tool in tools:
            assert isinstance(tool.description, str), (
                f"Tool '{tool.name}' description is not a string"
            )


# ---------------------------------------------------------------------------
# Parameters (JSON Schema)
# ---------------------------------------------------------------------------


class TestToolParameterSchemas:
    def test_all_tools_have_parameters_dict(self, tools):
        for tool in tools:
            assert isinstance(tool.parameters, dict), (
                f"Tool '{tool.name}' parameters is not a dict"
            )

    def test_all_parameters_have_type_object(self, tools):
        for tool in tools:
            assert tool.parameters.get("type") == "object", (
                f"Tool '{tool.name}' parameters.type is not 'object'"
            )

    def test_all_parameters_have_properties(self, tools):
        for tool in tools:
            assert "properties" in tool.parameters, (
                f"Tool '{tool.name}' parameters missing 'properties'"
            )
            assert isinstance(tool.parameters["properties"], dict)

    def test_required_fields_are_lists(self, tools):
        for tool in tools:
            required = tool.parameters.get("required")
            if required is not None:
                assert isinstance(required, list), (
                    f"Tool '{tool.name}' required is not a list"
                )

    def test_required_fields_reference_valid_properties(self, tools):
        for tool in tools:
            props = set(tool.parameters.get("properties", {}).keys())
            required = tool.parameters.get("required", [])
            for field in required:
                assert field in props, (
                    f"Tool '{tool.name}' required field '{field}' not in properties"
                )

    def test_each_property_has_type_or_enum(self, tools):
        for tool in tools:
            for prop_name, prop_schema in tool.parameters["properties"].items():
                has_type = "type" in prop_schema
                has_enum = "enum" in prop_schema
                assert has_type or has_enum, (
                    f"Tool '{tool.name}' property '{prop_name}' has no type or enum"
                )

    def test_parameters_are_json_serializable(self, tools):
        for tool in tools:
            try:
                json.dumps(tool.parameters)
            except (TypeError, ValueError) as e:
                pytest.fail(f"Tool '{tool.name}' parameters are not JSON-serializable: {e}")


# ---------------------------------------------------------------------------
# Per-tool required fields sanity checks
# ---------------------------------------------------------------------------


class TestToolRequiredFields:
    def _get_tool(self, tools, name: str) -> AgentTool:
        for t in tools:
            if t.name == name:
                return t
        pytest.fail(f"Tool '{name}' not found")

    def test_browse_evidence_requires_source_type(self, tools):
        t = self._get_tool(tools, "browse_evidence")
        assert "source_type" in t.parameters["required"]

    def test_search_evidence_requires_query(self, tools):
        t = self._get_tool(tools, "search_evidence")
        assert "query" in t.parameters["required"]

    def test_read_item_requires_item_id(self, tools):
        t = self._get_tool(tools, "read_item")
        assert "item_id" in t.parameters["required"]

    def test_save_finding_requires_category_and_content(self, tools):
        t = self._get_tool(tools, "save_finding")
        assert "category" in t.parameters["required"]
        assert "content" in t.parameters["required"]

    def test_save_memory_requires_category_and_content(self, tools):
        t = self._get_tool(tools, "save_memory")
        assert "category" in t.parameters["required"]
        assert "content" in t.parameters["required"]

    def test_save_quote_requires_quote_context_significance(self, tools):
        t = self._get_tool(tools, "save_quote")
        required = t.parameters["required"]
        assert "quote" in required
        assert "context" in required
        assert "significance" in required

    def test_save_knowledge_node_requires_name_and_type(self, tools):
        t = self._get_tool(tools, "save_knowledge_node")
        required = t.parameters["required"]
        assert "name" in required
        assert "type" in required

    def test_save_knowledge_edge_requires_source_target_relation(self, tools):
        t = self._get_tool(tools, "save_knowledge_edge")
        required = t.parameters["required"]
        assert "source_node" in required
        assert "target_node" in required
        assert "relation" in required

    def test_save_principle_requires_trigger_action_value(self, tools):
        t = self._get_tool(tools, "save_principle")
        required = t.parameters["required"]
        assert "trigger" in required
        assert "action" in required
        assert "value" in required

    def test_mark_explored_requires_item_id(self, tools):
        t = self._get_tool(tools, "mark_explored")
        assert "item_id" in t.parameters["required"]

    def test_get_progress_has_empty_properties(self, tools):
        t = self._get_tool(tools, "get_progress")
        assert t.parameters["properties"] == {}

    def test_finish_requires_summary(self, tools):
        t = self._get_tool(tools, "finish")
        assert "summary" in t.parameters["required"]


# ---------------------------------------------------------------------------
# Handlers are async callables
# ---------------------------------------------------------------------------


class TestToolHandlers:
    def test_all_handlers_are_callable(self, tools):
        for tool in tools:
            assert callable(tool.handler), f"Tool '{tool.name}' handler is not callable"

    def test_all_handlers_are_async(self, tools):
        for tool in tools:
            assert inspect.iscoroutinefunction(tool.handler), (
                f"Tool '{tool.name}' handler is not async"
            )


# ---------------------------------------------------------------------------
# Handler invocation — minimal happy-path (mocked DB)
# ---------------------------------------------------------------------------


class TestToolHandlerInvocation:
    @pytest.mark.asyncio
    async def test_browse_evidence_returns_json(self, tools, mock_session):
        tool = next(t for t in tools if t.name == "browse_evidence")
        result = await tool.handler(source_type="github", page=1, page_size=10)
        data = json.loads(result)
        assert "items" in data
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_search_evidence_returns_json(self, tools, mock_session):
        tool = next(t for t in tools if t.name == "search_evidence")
        result = await tool.handler(query="test")
        data = json.loads(result)
        assert "matches" in data
        assert data["query"] == "test"

    @pytest.mark.asyncio
    async def test_read_item_not_found_returns_error_json(self, tools, mock_session):
        tool = next(t for t in tools if t.name == "read_item")
        result = await tool.handler(item_id="nonexistent-id")
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_get_progress_no_record_returns_error(self, tools, mock_session):
        tool = next(t for t in tools if t.name == "get_progress")
        result = await tool.handler()
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_finish_returns_completed(self, tools, mock_session):
        # mock_session.execute for update — rowcount
        mock_session.execute = AsyncMock()
        tool = next(t for t in tools if t.name == "finish")
        result = await tool.handler(summary="All done.")
        data = json.loads(result)
        assert data["completed"] is True
        assert data["summary"] == "All done."

    @pytest.mark.asyncio
    async def test_save_knowledge_node_invalid_type_returns_error(self, tools, mock_session):
        tool = next(t for t in tools if t.name == "save_knowledge_node")
        result = await tool.handler(name="React", type="invalid_type")
        data = json.loads(result)
        assert "error" in data
        assert "Invalid type" in data["error"]

    @pytest.mark.asyncio
    async def test_save_knowledge_edge_invalid_relation_returns_error(self, tools, mock_session):
        tool = next(t for t in tools if t.name == "save_knowledge_edge")
        result = await tool.handler(
            source_node="Python",
            target_node="FastAPI",
            relation="invalid_relation",
        )
        data = json.loads(result)
        assert "error" in data
        assert "Invalid relation" in data["error"]

    @pytest.mark.asyncio
    async def test_mark_explored_not_found_returns_error(self, tools, mock_session):
        # Simulate rowcount == 0
        update_result = MagicMock()
        update_result.rowcount = 0
        mock_session.execute = AsyncMock(return_value=update_result)
        tool = next(t for t in tools if t.name == "mark_explored")
        result = await tool.handler(item_id="bad-id")
        data = json.loads(result)
        assert "error" in data
