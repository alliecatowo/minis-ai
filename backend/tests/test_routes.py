"""Endpoint tests for all FastAPI routes.

Uses httpx.AsyncClient with ASGITransport so no real server is needed.
Database and auth dependencies are overridden to avoid real connections.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Auto-use fixture: clear the IP rate limit window before every test so the
# in-memory sliding window doesn't accumulate across the test suite.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_ip_rate_limit_windows():
    """Clear the shared in-memory rate limit state before each test."""
    import app.middleware.ip_rate_limit as _rl
    _rl._windows.clear()
    yield
    _rl._windows.clear()


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_user(username: str = "testuser") -> MagicMock:
    """Create a minimal mock User for dependency overrides."""
    user = MagicMock()
    user.id = str(uuid.uuid4())
    user.github_username = username
    user.display_name = username
    user.avatar_url = None
    return user


def _make_session() -> AsyncMock:
    """Create a minimal mock AsyncSession that returns empty results."""
    session = AsyncMock()
    # .execute(...) -> result with scalars().all() -> []
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalars.return_value.first.return_value = None
    result.scalar_one_or_none.return_value = None
    result.scalar_one.return_value = 0
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    return session


async def _get_test_client(user=None, session=None):
    """Return an AsyncClient with optional dependency overrides applied."""
    from app.main import app
    from app.core.auth import get_current_user, get_optional_user
    from app.db import get_session

    overrides = {}
    if user is not None:
        overrides[get_current_user] = lambda: user
        overrides[get_optional_user] = lambda: user
    else:
        overrides[get_optional_user] = lambda: None

    if session is not None:
        overrides[get_session] = lambda: session

    app.dependency_overrides.update(overrides)
    return app


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health():
    """GET /api/health should return 200 with status=ok."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/health")

    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /api/minis — list public minis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_minis_returns_empty_list():
    """GET /api/minis should return a list (empty if no DB records)."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_list_minis_mine_requires_auth():
    """GET /api/minis?mine=true should return 401 when unauthenticated."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis?mine=true")

    app.dependency_overrides.clear()

    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/minis/by-username/{username} — lookup by username
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_mini_by_username_not_found():
    """GET /api/minis/by-username/nonexistent should return 404."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/by-username/nonexistent-user-xyz")

    app.dependency_overrides.clear()

    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /api/minis — create mini (requires auth)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_mini_requires_auth():
    """POST /api/minis without auth token should return 401."""
    from app.main import app

    # No override: get_current_user will raise 401
    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/minis", json={"username": "torvalds"})

    assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/minis/{id}/graph — knowledge graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_mini_graph_not_found():
    """GET /api/minis/{id}/graph with unknown ID should return 404."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    session = _make_session()

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/does-not-exist-abc123/graph")

    app.dependency_overrides.clear()

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_mini_graph_no_graph_returns_404():
    """GET /api/minis/{id}/graph when mini exists but has no graph should return 404."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = MagicMock()
    mini.id = str(uuid.uuid4())
    mini.username = "testuser"
    mini.visibility = "public"
    mini.owner_id = "owner-1"
    mini.knowledge_graph_json = None
    mini.principles_json = None

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini.id}/graph")

    app.dependency_overrides.clear()

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_mini_graph_returns_data():
    """GET /api/minis/{id}/graph when graph exists should return 200 with graph data."""
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini_id = str(uuid.uuid4())
    mini = MagicMock()
    mini.id = mini_id
    mini.username = "testuser"
    mini.visibility = "public"
    mini.owner_id = "owner-1"
    mini.knowledge_graph_json = {"nodes": [{"id": "python", "type": "skill"}], "edges": []}
    mini.principles_json = {"principles": []}

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result)

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/api/minis/{mini_id}/graph")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["mini_id"] == mini_id
    assert "knowledge_graph" in body
    assert "principles" in body


# ---------------------------------------------------------------------------
# GET /api/settings — requires auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_requires_auth():
    """GET /api/settings without auth should return 401."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_get_settings_authenticated_no_settings():
    """GET /api/settings with auth and no stored settings returns default gemini settings."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    session = _make_session()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["llm_provider"] == "gemini"
    assert body["has_api_key"] is False


# ---------------------------------------------------------------------------
# POST /api/auth/sync — requires X-Internal-Secret header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_sync_missing_secret_returns_401():
    """POST /api/auth/sync without X-Internal-Secret should return 401."""
    from app.main import app
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": "user-abc", "github_username": "testuser"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_sync_wrong_secret_returns_401():
    """POST /api/auth/sync with wrong X-Internal-Secret should return 401."""
    from app.main import app
    from app.db import get_session

    session = _make_session()
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": "user-abc", "github_username": "testuser"},
            headers={"X-Internal-Secret": "definitely-wrong-secret"},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_sync_correct_secret_upserts_user():
    """POST /api/auth/sync with correct X-Internal-Secret upserts user and returns user_id."""
    from app.main import app
    from app.core.config import settings
    from app.db import get_session

    user_id = str(uuid.uuid4())
    user_mock = MagicMock()
    user_mock.id = user_id
    user_mock.github_username = "testuser"
    user_mock.display_name = "Test User"
    user_mock.avatar_url = None

    session = _make_session()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None  # New user
    session.execute = AsyncMock(return_value=result)

    # After refresh, user.id should be set — simulate by returning our mock on refresh
    async def _refresh(obj):
        obj.id = user_id

    session.refresh = AsyncMock(side_effect=_refresh)

    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/api/auth/sync",
            json={"neon_auth_id": user_id, "github_username": "testuser"},
            headers={"X-Internal-Secret": settings.internal_api_secret},
        )

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert "user_id" in body


# ---------------------------------------------------------------------------
# GET /api/minis/sources — no auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_no_auth():
    """GET /api/minis/sources should return a list (plugins may not be loaded in test env)."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/sources")

    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    # Each source entry should have id, name, available fields
    for source in body:
        assert "id" in source
        assert "name" in source
        assert "available" in source


# ---------------------------------------------------------------------------
# GET /api/settings/models — no auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_available_models_no_auth():
    """GET /api/settings/models should return model catalogue without auth."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings/models")

    assert r.status_code == 200
    body = r.json()
    assert "gemini" in body
    assert "openai" in body
    assert "anthropic" in body


# ---------------------------------------------------------------------------
# GET /api/settings/models/tiers — no auth required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tier_models_no_auth():
    """GET /api/settings/models/tiers should return tier model catalogue without auth."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/settings/models/tiers")

    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert "tiers" in body
    assert "defaults" in body


# ---------------------------------------------------------------------------
# GET /api/auth/me — requires auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_me_requires_auth():
    """GET /api/auth/me without auth should return 401."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/auth/me")

    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_me_authenticated():
    """GET /api/auth/me with auth should return user info."""
    from app.main import app
    from app.core.auth import get_current_user

    user = _make_user("octocat")

    app.dependency_overrides[get_current_user] = lambda: user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/auth/me")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    body = r.json()
    assert body["github_username"] == "octocat"
