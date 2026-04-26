from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_chat_prompt_excludes_memory_blob_and_includes_retrieval_hint():
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini_id = str(uuid.uuid4())
    memory_blob = "PRIVATE_MEMORY_BLOB_DO_NOT_INJECT"

    mini = MagicMock()
    mini.id = mini_id
    mini.username = "testdev"
    mini.status = "ready"
    mini.visibility = "public"
    mini.owner_id = str(uuid.uuid4())
    mini.system_prompt = (
        "# IDENTITY DIRECTIVE\n\nYou are testdev.\n\n"
        "# KNOWLEDGE\n\nPRIVATE_MEMORY_BLOB_DO_NOT_INJECT\n"
    )
    mini.spirit_content = "You are concise and pragmatic."
    mini.memory_content = memory_blob
    mini.evidence_cache = None
    mini.knowledge_graph_json = None
    mini.principles_json = None
    mini.motivations_json = None

    session = MagicMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result_mock)
    session.commit = AsyncMock()

    captured_prompts: list[str] = []

    async def _fake_stream(**kwargs):
        captured_prompts.append(kwargs.get("system_prompt", ""))
        return
        yield

    with patch("app.routes.chat.run_agent_streaming", side_effect=_fake_stream):
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_optional_user] = lambda: None

        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/api/minis/{mini_id}/chat",
                json={"message": "What do you think about async helpers?"},
            )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured_prompts
    prompt = captured_prompts[0]
    assert memory_blob not in prompt
    assert "Use search_memories to retrieve relevant memories and search_evidence for source evidence." in prompt
    assert "You are concise and pragmatic." in prompt
