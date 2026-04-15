"""Agent framework built on PydanticAI.

Provides helper functions that wrap PydanticAI's Agent to yield AgentEvent
objects compatible with the frontend SSE protocol.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    RunContext,
    TextPartDelta,
    FinalResultEvent,
)
from pydantic_ai.toolsets import FunctionToolset

from app.core.compaction import create_compaction_processor
from app.core.models import ModelTier, get_model

logger = logging.getLogger(__name__)


@dataclass
class AgentTool:
    """A tool the agent can call.

    Kept for backward compatibility with callers that build tool lists
    (explorers, chat, chief synthesizer). Converted to PydanticAI
    FunctionToolset at agent run time.
    """

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Any  # async callable(kwargs) -> str


@dataclass
class AgentResult:
    """Result of an agent run."""

    final_response: str | None
    tool_outputs: dict[str, list[Any]] = field(default_factory=dict)
    turns_used: int = 0


@dataclass
class AgentEvent:
    """An event from the agent streaming loop.

    Types: "tool_call", "tool_result", "chunk", "done", "error"
    The frontend SSE protocol depends on these exact type strings.
    """

    type: str  # "tool_call", "tool_result", "chunk", "done", "error"
    data: str


def _build_toolset(tools: list[AgentTool]) -> FunctionToolset:
    """Convert AgentTool list to a PydanticAI FunctionToolset."""
    toolset = FunctionToolset()
    for tool in tools:
        # Create a closure that captures the specific handler
        handler = tool.handler

        # PydanticAI tool_plain registers a function by name.
        # We need to create wrapper functions dynamically.
        async def _make_handler(h=handler, **kwargs):
            result = await h(**kwargs)
            return str(result) if result is not None else "OK"

        # Register using the low-level API
        toolset.tool_plain(
            _make_handler,
            name=tool.name,
            description=tool.description,
            json_schema=tool.parameters,
        )

    return toolset


def _build_agent(
    system_prompt: str,
    tools: list[AgentTool],
    model: str | None = None,
) -> Agent:
    """Build a PydanticAI Agent from system prompt and AgentTool list."""
    resolved_model = model or get_model(ModelTier.STANDARD)
    toolset = _build_toolset(tools)

    processor = create_compaction_processor(resolved_model)
    history_processors = [processor] if processor else None

    agent = Agent(
        resolved_model,
        instructions=system_prompt,
        toolsets=[toolset],
        output_type=str,
        history_processors=history_processors,
    )
    return agent


async def run_agent(
    system_prompt: str,
    user_prompt: str,
    tools: list[AgentTool],
    max_turns: int = 10,
    model: str | None = None,
    api_key: str | None = None,
    max_output_tokens: int | None = None,
    tool_choice_strategy: str = "auto_after_first",
    finish_tool_name: str | None = "finish",
) -> AgentResult:
    """Run an agent loop using PydanticAI.

    Wraps PydanticAI's Agent.run() to maintain the same interface as the
    old hand-rolled ReAct loop. The agent decides when it's done.
    """
    resolved_model = model or get_model(ModelTier.STANDARD)
    tool_handlers = {t.name: t.handler for t in tools}
    tool_outputs: dict[str, list[Any]] = {t.name: [] for t in tools}

    # Build the toolset with tracking
    toolset = FunctionToolset()
    finished = False
    finish_rejected = False

    for tool in tools:
        _handler = tool.handler
        _name = tool.name

        async def _wrapper(
            _h=_handler, _n=_name, **kwargs
        ) -> str:
            nonlocal finished, finish_rejected
            result = await _h(**kwargs)
            result_str = str(result) if result is not None else "OK"
            tool_outputs.setdefault(_n, []).append(kwargs)

            # Track finish tool behavior
            if _n == finish_tool_name:
                if result_str.startswith("NOT YET"):
                    finish_rejected = True
                else:
                    finished = True

            return result_str

        toolset.tool_plain(
            _wrapper,
            name=tool.name,
            description=tool.description,
            json_schema=tool.parameters,
        )

    processor = create_compaction_processor(resolved_model)
    history_processors = [processor] if processor else None

    agent = Agent(
        resolved_model,
        instructions=system_prompt,
        toolsets=[toolset],
        output_type=str,
        history_processors=history_processors,
    )

    try:
        result = await agent.run(user_prompt)
        return AgentResult(
            final_response=result.output,
            tool_outputs=tool_outputs,
            turns_used=result.usage().requests,
        )
    except Exception as e:
        logger.error("Agent run failed: %s", e)
        return AgentResult(
            final_response=None,
            tool_outputs=tool_outputs,
            turns_used=0,
        )


async def run_agent_streaming(
    system_prompt: str,
    user_prompt: str,
    tools: list[AgentTool],
    history: list[dict] | None = None,
    max_turns: int = 5,
    model: str | None = None,
    api_key: str | None = None,
    max_output_tokens: int | None = None,
    tool_choice_strategy: str = "auto_after_first",
    finish_tool_name: str | None = "finish",
) -> AsyncGenerator[AgentEvent, None]:
    """Run an agent loop with streaming output, yielding AgentEvent objects.

    Uses PydanticAI's run_stream_events() to iterate over all events
    (tool calls, tool results, text deltas) and translates them into
    AgentEvent objects that the frontend SSE protocol expects.
    """
    resolved_model = model or get_model(ModelTier.STANDARD)
    tool_outputs: dict[str, list[Any]] = {t.name: [] for t in tools}

    # Build toolset with tracking
    toolset = FunctionToolset()

    for tool in tools:
        _handler = tool.handler
        _name = tool.name

        async def _wrapper(
            _h=_handler, _n=_name, **kwargs
        ) -> str:
            result = await _h(**kwargs)
            result_str = str(result) if result is not None else "OK"
            tool_outputs.setdefault(_n, []).append(kwargs)
            return result_str

        toolset.tool_plain(
            _wrapper,
            name=tool.name,
            description=tool.description,
            json_schema=tool.parameters,
        )

    # Build message history for multi-turn chat
    message_history = None
    if history:
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            TextPart,
            UserPromptPart,
        )

        message_history = []
        for msg in history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                message_history.append(
                    ModelRequest(parts=[UserPromptPart(content=content)])
                )
            elif role == "assistant":
                message_history.append(
                    ModelResponse(parts=[TextPart(content=content)])
                )

    processor = create_compaction_processor(resolved_model)
    history_processors = [processor] if processor else None

    agent = Agent(
        resolved_model,
        instructions=system_prompt,
        toolsets=[toolset],
        output_type=str,
        history_processors=history_processors,
    )

    try:
        async for event in agent.run_stream_events(
            user_prompt,
            message_history=message_history,
        ):
            if isinstance(event, AgentRunResultEvent):
                # Final result — we already streamed the text via deltas
                pass
            elif isinstance(event, FunctionToolCallEvent):
                # Tool is being called
                try:
                    args = event.part.args
                    if isinstance(args, str):
                        args = json.loads(args)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                yield AgentEvent(
                    type="tool_call",
                    data=json.dumps({"tool": event.part.tool_name, "args": args}),
                )
            elif isinstance(event, FunctionToolResultEvent):
                # Tool returned a result
                result_content = str(event.result.content) if event.result else ""
                yield AgentEvent(
                    type="tool_result",
                    data=json.dumps({
                        "tool": event.tool_name,
                        "summary": result_content[:200],
                    }),
                )
            elif isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta):
                    yield AgentEvent(
                        type="chunk",
                        data=event.delta.content_delta,
                    )
            # PartStartEvent, FinalResultEvent, etc. are handled implicitly

    except Exception as e:
        logger.error("Streaming agent failed: %s", e)
        yield AgentEvent(type="error", data=str(e))
        return

    yield AgentEvent(type="done", data="")
