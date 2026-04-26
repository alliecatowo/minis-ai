from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mini(memory_content: str | None = None, evidence_cache: str | None = None) -> MagicMock:
    mini = MagicMock()
    mini.id = str(uuid.uuid4())
    mini.username = "testdev"
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


class TestSemanticMemorySearch:
    @pytest.mark.asyncio
    async def test_search_memories_semantic_match_without_verbatim_term(self):
        from app.routes.chat import _build_chat_tools

        mini = _make_mini(
            memory_content="I focus on lock-free queue design and deterministic testing.",
            evidence_cache="",
        )
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(
            return_value=_make_result(
                [
                    (
                        "explorer_findings",
                        "mem-123",
                        0,
                        "I focus on lock-free queue design and deterministic testing.",
                        0.08,
                    )
                ]
            )
        )

        with (
            patch("app.routes.chat._VECTOR_SEARCH_AVAILABLE", True),
            patch("app.routes.chat.embed_texts", AsyncMock(return_value=[[0.1] * 1536])),
        ):
            tools = _build_chat_tools(mini, session=mock_session)
            mem_tool = next(t for t in tools if t.name == "search_memories")
            result = await mem_tool.handler("How do you prevent race conditions?")

        assert "memory_id=mem-123" in result
        assert "relevance=" in result
        assert "lock-free queue" in result

    @pytest.mark.asyncio
    async def test_search_memories_keyword_fallback_when_embeddings_empty(self):
        from app.routes.chat import _build_chat_tools

        mini = _make_mini(memory_content="Python async review notes", evidence_cache="")
        mock_session = MagicMock()
        mock_session.execute = AsyncMock(return_value=_make_result([]))

        with (
            patch("app.routes.chat._VECTOR_SEARCH_AVAILABLE", True),
            patch("app.routes.chat.embed_texts", AsyncMock(return_value=[[0.1] * 1536])),
        ):
            tools = _build_chat_tools(mini, session=mock_session)
            mem_tool = next(t for t in tools if t.name == "search_memories")
            result = await mem_tool.handler("Python")

        assert "Python async review notes" in result
