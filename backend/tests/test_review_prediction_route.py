from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _session_with_mini(mini):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result)
    return session


def _mini(**overrides) -> SimpleNamespace:
    data = {
        "id": "mini-123",
        "username": "reviewer",
        "display_name": "Reviewer",
        "avatar_url": None,
        "owner_id": "owner-1",
        "visibility": "public",
        "org_id": None,
        "bio": None,
        "spirit_content": None,
        "memory_content": "Pushes for tests and rollback plans in code review.",
        "personality_typology_json": None,
        "behavioral_context_json": {
            "summary": "Direct in code review.",
            "contexts": [
                {
                    "context": "code_review",
                    "summary": "Flags missing tests and unclear rollout plans.",
                    "behaviors": ["asks for tests", "asks for rollout safety"],
                }
            ],
        },
        "motivations_json": {
            "motivations": [],
            "motivation_chains": [],
            "summary": "Values code quality.",
        },
        "values_json": {
            "engineering_values": [
                {"name": "Code Quality", "description": "", "intensity": 8.0},
                {"name": "Directness", "description": "", "intensity": 7.0},
                {"name": "Pragmatism", "description": "", "intensity": 5.0},
            ]
        },
        "roles_json": None,
        "skills_json": None,
        "traits_json": None,
        "metadata_json": None,
        "sources_used": None,
        "system_prompt": None,
        "evidence_cache": "review: add tests before merge",
        "status": "ready",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
async def test_review_prediction_endpoint_returns_structured_payload(app):
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _mini()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/review-prediction",
            json={
                "title": "Update auth flow",
                "description": "Touches token validation and queue retries.",
                "changed_files": ["backend/app/auth.py"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "review_prediction_v1"
    assert body["reviewer_username"] == "reviewer"
    assert "private_assessment" in body
    assert "delivery_policy" in body
    assert "expressed_feedback" in body


@pytest.mark.asyncio
async def test_review_prediction_endpoint_respects_private_access(app, mock_user):
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _mini(visibility="private", owner_id="someone-else")
    app.dependency_overrides[get_optional_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/review-prediction",
            json={"title": "Update auth flow"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_review_prediction_endpoint_infers_delivery_context_from_request(app):
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _mini()
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini(mini)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/minis/{mini.id}/review-prediction",
            json={
                "title": "WIP prototype for ingestion retries",
                "description": "Draft experiment to explore queue semantics before hardening them.",
                "changed_files": ["backend/app/ingestion/github.py"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["delivery_policy"]["context"] == "exploratory"
    assert body["delivery_policy"]["teaching_mode"] is True
