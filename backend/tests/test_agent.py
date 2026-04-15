"""Tests for backend/app/core/agent.py — pure function tests."""

from __future__ import annotations

from app.core.agent import AgentTool, AgentEvent, AgentResult


# ── AgentTool ───────────────────────────────────────────────────────


class TestAgentTool:
    def test_creates_tool(self):
        tool = AgentTool(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            handler=None,
        )
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
        assert tool.parameters == {"type": "object", "properties": {}}

    def test_multiple_tools(self):
        tools = [
            AgentTool(name=f"tool_{i}", description=f"Tool {i}", parameters={}, handler=None)
            for i in range(3)
        ]
        assert len(tools) == 3
        names = [t.name for t in tools]
        assert names == ["tool_0", "tool_1", "tool_2"]


# ── AgentEvent ──────────────────────────────────────────────────────


class TestAgentEvent:
    def test_event_types(self):
        for event_type in ("tool_call", "tool_result", "chunk", "done", "error"):
            event = AgentEvent(type=event_type, data="test")
            assert event.type == event_type
            assert event.data == "test"


# ── AgentResult ─────────────────────────────────────────────────────


class TestAgentResult:
    def test_default_result(self):
        result = AgentResult(final_response="Hello")
        assert result.final_response == "Hello"
        assert result.tool_outputs == {}
        assert result.turns_used == 0

    def test_result_with_tool_outputs(self):
        result = AgentResult(
            final_response=None,
            tool_outputs={"save_memory": [{"topic": "test"}]},
            turns_used=5,
        )
        assert result.final_response is None
        assert len(result.tool_outputs["save_memory"]) == 1
        assert result.turns_used == 5
