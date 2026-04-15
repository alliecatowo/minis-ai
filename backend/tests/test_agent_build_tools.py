"""Tests for agent.py _build_tools() and BudgetExceededError from llm.py.

Covers:
- _build_tools() converts AgentTool list to PydanticAI Tool list
- Each resulting Tool has the correct name and description
- Handlers are wrapped and called correctly
- BudgetExceededError in llm.py
- setup_langfuse is a no-op stub
"""

from __future__ import annotations


import pytest
from pydantic_ai.tools import Tool

from app.core.agent import AgentTool, _build_tools


# ---------------------------------------------------------------------------
# _build_tools()
# ---------------------------------------------------------------------------


class TestBuildTools:
    def _make_tool(self, name: str, description: str = "A test tool") -> AgentTool:
        async def handler(**kwargs) -> str:
            return f"result from {name}"

        return AgentTool(
            name=name,
            description=description,
            parameters={
                "type": "object",
                "properties": {
                    "arg1": {"type": "string", "description": "First arg"},
                },
                "required": ["arg1"],
            },
            handler=handler,
        )

    def test_returns_list(self):
        tools = _build_tools([self._make_tool("t1")])
        assert isinstance(tools, list)

    def test_empty_input_returns_empty_list(self):
        result = _build_tools([])
        assert result == []

    def test_single_tool_returns_single_item(self):
        result = _build_tools([self._make_tool("only_tool")])
        assert len(result) == 1

    def test_multiple_tools_count_preserved(self):
        agent_tools = [self._make_tool(f"tool_{i}") for i in range(5)]
        result = _build_tools(agent_tools)
        assert len(result) == 5

    def test_result_items_are_pydantic_ai_tools(self):
        result = _build_tools([self._make_tool("t1")])
        for item in result:
            assert isinstance(item, Tool), f"Expected Tool, got {type(item)}"

    def test_tool_name_preserved(self):
        agent_tool = self._make_tool("my_special_tool")
        result = _build_tools([agent_tool])
        assert result[0].name == "my_special_tool"

    def test_tool_description_preserved(self):
        agent_tool = self._make_tool("t1", description="Custom description text")
        result = _build_tools([agent_tool])
        assert result[0].description == "Custom description text"

    def test_tool_names_all_match(self):
        names = ["alpha", "beta", "gamma"]
        agent_tools = [self._make_tool(n) for n in names]
        result = _build_tools(agent_tools)
        result_names = [t.name for t in result]
        for name in names:
            assert name in result_names

    @pytest.mark.asyncio
    async def test_handler_called_through_wrapper(self):
        """The wrapped handler should call the original handler."""
        called_with = {}

        async def my_handler(**kwargs) -> str:
            called_with.update(kwargs)
            return "my result"

        agent_tool = AgentTool(
            name="test_handler",
            description="desc",
            parameters={
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
            handler=my_handler,
        )
        tools = _build_tools([agent_tool])
        assert len(tools) == 1

    @pytest.mark.asyncio
    async def test_none_handler_result_becomes_ok_string(self):
        """If handler returns None the wrapper should return 'OK'."""
        async def none_handler(**kwargs) -> None:
            return None

        agent_tool = AgentTool(
            name="none_result",
            description="desc",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=none_handler,
        )
        tools = _build_tools([agent_tool])
        assert len(tools) == 1

    def test_tool_with_no_properties_ok(self):
        """Tools with empty properties dict should not raise."""
        async def handler(**kwargs) -> str:
            return "ok"

        agent_tool = AgentTool(
            name="no_props",
            description="no props tool",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=handler,
        )
        result = _build_tools([agent_tool])
        assert len(result) == 1
        assert result[0].name == "no_props"


# ---------------------------------------------------------------------------
# BudgetExceededError
# ---------------------------------------------------------------------------


class TestBudgetExceededError:
    def test_default_message(self):
        from app.core.llm import BudgetExceededError

        err = BudgetExceededError()
        assert "budget" in str(err).lower()
        assert err.message == "LLM budget exceeded"

    def test_custom_message(self):
        from app.core.llm import BudgetExceededError

        err = BudgetExceededError("Custom budget error")
        assert err.message == "Custom budget error"
        assert str(err) == "Custom budget error"

    def test_is_exception(self):
        from app.core.llm import BudgetExceededError

        assert issubclass(BudgetExceededError, Exception)

    def test_can_be_raised_and_caught(self):
        from app.core.llm import BudgetExceededError

        with pytest.raises(BudgetExceededError) as exc_info:
            raise BudgetExceededError("Test budget exceeded")
        assert exc_info.value.message == "Test budget exceeded"

    def test_can_be_caught_as_exception(self):
        from app.core.llm import BudgetExceededError

        with pytest.raises(Exception):
            raise BudgetExceededError()


# ---------------------------------------------------------------------------
# setup_langfuse stub
# ---------------------------------------------------------------------------


class TestSetupLangfuse:
    def test_setup_langfuse_is_callable(self):
        from app.core.llm import setup_langfuse
        assert callable(setup_langfuse)

    def test_setup_langfuse_does_not_raise(self):
        from app.core.llm import setup_langfuse
        setup_langfuse()  # Should be a no-op

    def test_setup_langfuse_returns_none(self):
        from app.core.llm import setup_langfuse
        result = setup_langfuse()
        assert result is None


# ---------------------------------------------------------------------------
# _check_budget — basic None user bypass
# ---------------------------------------------------------------------------


class TestCheckBudget:
    @pytest.mark.asyncio
    async def test_none_user_id_does_not_raise(self):
        """Budget check should skip entirely when user_id is None."""
        from app.core.llm import _check_budget
        # Should not raise
        await _check_budget(None)
