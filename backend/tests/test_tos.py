from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = "user-123"
    user.github_username = "octocat"
    user.display_name = "Octo Cat"
    user.avatar_url = "https://github.com/octocat.png"
    return user


def _make_session(*scalar_results):
    session = AsyncMock()
    execute_results = []
    for value in scalar_results:
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        execute_results.append(result)
    session.execute = AsyncMock(side_effect=execute_results)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_accept_tos_creates_row_and_returns_accepted_true():
    from app.core.auth import get_current_user
    from app.db import get_session
    from app.main import app

    user = _make_user()
    session = _make_session()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/auth/accept-tos")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["version"] == "2026-04-26"
    session.add.assert_called_once()
    created = session.add.call_args.args[0]
    assert created.user_id == user.id
    assert created.version == "2026-04-26"
    assert created.accepted_at is not None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_me_returns_null_tos_version_when_no_acceptance():
    from app.core.auth import get_current_user
    from app.db import get_session
    from app.main import app

    user = _make_user()
    session = _make_session(None)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/auth/me")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["tos_version_accepted"] is None


@pytest.mark.asyncio
async def test_auth_me_returns_latest_tos_version_when_acceptance_exists():
    from app.core.auth import get_current_user
    from app.db import get_session
    from app.main import app

    user = _make_user()
    session = _make_session("2026-04-26")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/auth/me")

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["tos_version_accepted"] == "2026-04-26"
