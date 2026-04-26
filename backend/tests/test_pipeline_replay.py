from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

# Must be set before importing agent/cassette modules.
os.environ["MINIS_CASSETTE_MODE"] = "replay"
os.environ["MINIS_CASSETTE_RUN_ID"] = "default"

from app.core.agent import AgentTool, run_agent


@pytest.mark.asyncio
async def test_pipeline_replay_offline_with_default_cassettes() -> None:
    mock_mini = SimpleNamespace(
        system_prompt=(
            "You are a synthetic replay mini for deterministic CI checks. "
            "Use concise, practical answers, call tools when needed, and explain decisions in one short paragraph. "
            "Stay grounded in evidence and avoid speculative claims."
        )
    )

    assert isinstance(mock_mini.system_prompt, str)
    assert len(mock_mini.system_prompt) > 100

    async def save_memory(topic: str) -> str:
        return f"saved:{topic}"

    tool = AgentTool(
        name="save_memory",
        description="Persist a memory topic",
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
        handler=save_memory,
    )

    replay_with_tool = await run_agent(
        system_prompt=mock_mini.system_prompt,
        user_prompt="Analyze and call save_memory exactly once before the final answer.",
        tools=[tool],
        max_turns=5,
        model="openai:gpt-5-mini",
    )

    assert replay_with_tool.final_response is not None
    assert "Replay summary" in replay_with_tool.final_response
    assert replay_with_tool.tool_outputs["save_memory"]

    replay_simple = await run_agent(
        system_prompt=mock_mini.system_prompt,
        user_prompt="Return a short standalone replay confirmation.",
        tools=[],
        max_turns=3,
        model="openai:gpt-5-mini",
    )

    assert replay_simple.final_response is not None
    assert "standalone replay" in replay_simple.final_response
