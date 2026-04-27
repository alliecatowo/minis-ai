from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.review_predictor_agent import _build_predictor_tools


@pytest.mark.asyncio
async def test_predictor_search_memories_returns_hybrid_retrieval_signals():
    mini = MagicMock()
    mini.id = "mini-1"
    mini.memory_content = "I prioritize deterministic rollouts and quick rollback safety checks."
    mini.evidence_cache = ""
    mini.principles_json = {"principles": []}
    mini.knowledge_graph_json = None

    session = MagicMock()
    result = MagicMock()
    result.all.return_value = [
        (
            "explorer_findings",
            "mem-100",
            0,
            "I prioritize deterministic rollouts and quick rollback safety checks.",
            0.07,
        )
    ]
    session.execute = AsyncMock(return_value=result)

    with (
        patch("app.core.review_predictor_agent._PREDICTOR_VECTOR_AVAILABLE", True),
        patch("app.core.review_predictor_agent.embed_texts", AsyncMock(return_value=[[0.1] * 1536])),
    ):
        tools = _build_predictor_tools(mini, session)
        handler = next(t.handler for t in tools if t.name == "search_memories")
        output = await handler("How would you review rollout risk and rollback plans?")

    assert "relevance=" in output
    assert "semantic=" in output
    assert "lexical=" in output
    assert "provenance=" in output
    assert "citation=" in output


@pytest.mark.asyncio
async def test_predictor_tools_include_knowledge_graph_search():
    mini = MagicMock()
    mini.id = "mini-kg"
    mini.memory_content = ""
    mini.evidence_cache = ""
    mini.principles_json = {"principles": []}
    mini.knowledge_graph_json = {
        "nodes": [{"id": "rust", "name": "Rust", "type": "skill", "depth": 0.8}],
        "edges": [],
    }

    session = AsyncMock()
    tools = _build_predictor_tools(mini, session)

    handler = next(t.handler for t in tools if t.name == "search_knowledge_graph")
    output = await handler("Rust")

    assert "Rust" in output
