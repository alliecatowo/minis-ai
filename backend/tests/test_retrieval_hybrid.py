from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mini(memory_content: str | None = None, evidence_cache: str | None = None) -> MagicMock:
    mini = MagicMock()
    mini.id = str(uuid.uuid4())
    mini.username = "hybrid"
    mini.memory_content = memory_content
    mini.evidence_cache = evidence_cache
    mini.knowledge_graph_json = None
    mini.principles_json = None
    mini.motivations_json = None
    return mini


def _make_result(rows: list[tuple]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


@pytest.mark.asyncio
async def test_search_memories_uses_hybrid_signals_for_substantive_query():
    from app.routes.chat import _build_chat_tools

    mini = _make_mini(
        memory_content="I prefer deterministic race-condition reproductions with minimal fixtures.",
        evidence_cache="",
    )
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(
        return_value=_make_result(
            [
                (
                    "explorer_findings",
                    "mem-77",
                    0,
                    "I prefer deterministic race-condition reproductions with minimal fixtures.",
                    0.04,
                )
            ]
        )
    )

    with (
        patch("app.routes.chat._VECTOR_SEARCH_AVAILABLE", True),
        patch("app.routes.chat.embed_texts", AsyncMock(return_value=[[0.2] * 1536])),
    ):
        tools = _build_chat_tools(mini, session=mock_session)
        mem_tool = next(t for t in tools if t.name == "search_memories")
        result = await mem_tool.handler("How do you debug race conditions in async systems?")

    assert "relevance=" in result
    assert "semantic=" in result
    assert "lexical=" in result
    assert "provenance=" in result
    assert "memory_id=mem-77" in result


@pytest.mark.asyncio
async def test_search_evidence_hybrid_budget_is_deterministic_and_bounded():
    from app.routes.chat import _build_chat_tools

    evidence_lines = "\n".join(f"line {i} mentions python concurrency" for i in range(40))
    mini = _make_mini(memory_content="", evidence_cache=evidence_lines)

    with patch("app.routes.chat._VECTOR_SEARCH_AVAILABLE", False):
        tools = _build_chat_tools(mini, session=None)
        ev_tool = next(t for t in tools if t.name == "search_evidence")
        result = await ev_tool.handler("How do you choose Python concurrency patterns?")

    chunks = [part for part in result.split("\n\n---\n\n") if part.strip()]
    assert len(chunks) <= 8


def test_query_graph_supports_source_target_edges_and_citations():
    from app.routes.chat import query_graph_from_knowledge_graph

    graph = {
        "nodes": [{"id": "python", "name": "Python"}, {"id": "asyncio", "name": "Asyncio"}],
        "edges": [
            {
                "source": "python",
                "target": "asyncio",
                "relation": "uses",
                "evidence_ids": ["ev-1", "ev-2"],
            }
        ],
    }

    result = query_graph_from_knowledge_graph(
        knowledge_graph_json=graph,
        node_name="python",
        relation="uses",
        depth=2,
    )

    assert result["edges"][0]["from_node"] == "python"
    assert result["edges"][0]["to_node"] == "asyncio"
    assert result["edges"][0]["evidence_ids"] == ["ev-1", "ev-2"]
    assert result["citations"] == ["ev-1", "ev-2"]
