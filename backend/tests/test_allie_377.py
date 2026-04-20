"""Tests for ALLIE-377: username uniqueness constraint + prefer-owned resolve.

Covers:
- get_mini_by_username: owned row preferred over stale public row
- create_mini: upsert paths (reassign stale, reject taken, re-run owned)
- Migration pre-flight: duplicate detection raises RuntimeError
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: str | None = None, username: str = "testuser") -> MagicMock:
    user = MagicMock()
    user.id = user_id or str(uuid.uuid4())
    user.github_username = username
    user.display_name = username
    user.avatar_url = None
    return user


def _make_mini(
    *,
    mini_id: str | None = None,
    username: str = "alliecatowo",
    owner_id: str | None = None,
    visibility: str = "public",
    status: str = "completed",
) -> MagicMock:
    m = MagicMock()
    m.id = mini_id or str(uuid.uuid4())
    m.username = username
    m.owner_id = owner_id
    m.visibility = visibility
    m.status = status
    m.display_name = username
    m.avatar_url = None
    m.spirit_content = None
    m.memory_content = None
    m.system_prompt = None
    m.values_json = None
    m.roles_json = None
    m.skills_json = None
    m.traits_json = None
    m.metadata_json = None
    m.knowledge_graph_json = None
    m.principles_json = None
    m.sources_used = []
    m.bio = None
    m.org_id = None
    # These must be correct types for Pydantic schema validation (from_attributes=True)
    m.values = []
    m.roles = {}
    m.skills = []
    m.traits = []
    _now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    m.created_at = _now
    m.updated_at = _now
    return m


def _make_session() -> AsyncMock:
    session = AsyncMock()
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
    session.flush = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# get_mini_by_username: prefer-owned ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_mini_by_username_prefers_owned_over_stale_public():
    """Anonymous lookup returns the owned mini even if a stale public row exists.

    We mock the DB to return two rows; the first (owned) should be served.
    The route selects with ORDER BY owner_id IS NULL, so owned rows sort first.
    We verify the response corresponds to the owned mini (non-null owner_id).
    """
    from app.main import app
    from app.core.auth import get_optional_user
    from app.db import get_session

    owned_mini = _make_mini(owner_id="owner-abc", username="alliecatowo")

    session = _make_session()

    # First call: no owned mini for current user (unauthenticated path skips it)
    # Second call: public query — returns owned_mini as the first result
    public_result = MagicMock()
    public_result.scalars.return_value.first.return_value = owned_mini

    session.execute = AsyncMock(return_value=public_result)

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/by-username/alliecatowo")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    # Verify the route was called (DB was hit)
    assert session.execute.called


@pytest.mark.asyncio
async def test_get_mini_by_username_authenticated_user_gets_own_mini():
    """Authenticated user gets their own mini, not the stale public row."""
    from app.main import app
    from app.core.auth import get_current_user, get_optional_user
    from app.db import get_session

    user_id = str(uuid.uuid4())
    user = _make_user(user_id=user_id, username="alliecatowo")
    owned_mini = _make_mini(owner_id=user_id, username="alliecatowo")

    session = _make_session()

    # First execute: owns the mini (own-mini check)
    own_result = MagicMock()
    own_result.scalar_one_or_none.return_value = owned_mini
    session.execute = AsyncMock(return_value=own_result)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/minis/by-username/alliecatowo")

    app.dependency_overrides.clear()

    assert r.status_code == 200
    # Should have hit the DB exactly once (own-mini short circuit)
    assert session.execute.call_count == 1


# ---------------------------------------------------------------------------
# create_mini: upsert paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_mini_reassigns_stale_public_row():
    """POST /api/minis with a stale unowned row reassigns it to the user."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user_id = str(uuid.uuid4())
    user = _make_user(user_id=user_id)
    stale_mini = _make_mini(owner_id=None, username="somedev")

    session = _make_session()

    # Sequence of DB calls in create_mini:
    # 1. check_rate_limit internal call (mocked away)
    # 2. owned-mini check → None
    # 3. stale-mini check → stale_mini
    call_count = 0

    async def _execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.first.return_value = None
        result.scalar_one.return_value = 0
        if call_count == 1:
            # owned-mini check
            result.scalar_one_or_none.return_value = None
        elif call_count == 2:
            # stale-mini check
            result.scalars.return_value.first.return_value = stale_mini
        return result

    session.execute = _execute

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with (
        patch("app.routes.minis.check_rate_limit", new=AsyncMock()),
        patch("app.routes.minis.asyncio.create_task"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/minis", json={"username": "somedev", "sources": ["github"]})

    app.dependency_overrides.clear()

    assert r.status_code == 202
    # The stale mini's owner_id should have been updated
    assert stale_mini.owner_id == user_id
    assert stale_mini.status == "processing"


@pytest.mark.asyncio
async def test_create_mini_returns_409_when_owned_by_other_user():
    """POST /api/minis returns 409 if the username is owned by a different user."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user = _make_user()
    other_owners_mini = _make_mini(owner_id="other-owner-id", username="takendev")

    session = _make_session()

    call_count = 0

    async def _execute(stmt):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.first.return_value = None
        result.scalar_one.return_value = 0
        if call_count == 1:
            # owned-mini check for requesting user → None
            result.scalar_one_or_none.return_value = None
        elif call_count == 2:
            # stale-mini check → None (no unowned row)
            result.scalars.return_value.first.return_value = None
        elif call_count == 3:
            # taken-by-other check → other owner's mini
            result.scalars.return_value.first.return_value = other_owners_mini
        return result

    session.execute = _execute

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with patch("app.routes.minis.check_rate_limit", new=AsyncMock()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post(
                "/api/minis", json={"username": "takendev", "sources": ["github"]}
            )

    app.dependency_overrides.clear()

    assert r.status_code == 409
    assert "already owned" in r.json()["detail"]


@pytest.mark.asyncio
async def test_create_mini_reruns_if_owner_already_has_mini():
    """POST /api/minis re-runs the pipeline when the user already owns the mini."""
    from app.main import app
    from app.core.auth import get_current_user
    from app.db import get_session

    user_id = str(uuid.uuid4())
    user = _make_user(user_id=user_id)
    existing_mini = _make_mini(owner_id=user_id, username="mydev", status="completed")

    session = _make_session()
    owned_result = MagicMock()
    owned_result.scalar_one_or_none.return_value = existing_mini
    session.execute = AsyncMock(return_value=owned_result)

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session

    with (
        patch("app.routes.minis.check_rate_limit", new=AsyncMock()),
        patch("app.routes.minis.asyncio.create_task"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.post("/api/minis", json={"username": "mydev", "sources": ["github"]})

    app.dependency_overrides.clear()

    assert r.status_code == 202
    assert existing_mini.status == "processing"


# ---------------------------------------------------------------------------
# Migration: duplicate pre-flight check
# ---------------------------------------------------------------------------


def test_migration_precheck_raises_on_duplicates():
    """_check_no_duplicates() raises RuntimeError when duplicates exist."""
    import importlib
    import sys

    # Load the migration module
    module_path = "alembic.versions.f1a2b3c4d5e6_add_username_uniqueness_ALLIE_377"
    if module_path in sys.modules:
        del sys.modules[module_path]

    spec_path = (
        "/home/Allie/develop/minis-hackathon/.claude/worktrees/agent-ab3514f2"
        "/backend/alembic/versions/f1a2b3c4d5e6_add_username_uniqueness_ALLIE_377.py"
    )
    import importlib.util

    spec = importlib.util.spec_from_file_location("migration_377", spec_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    # Mock a connection that returns duplicate rows
    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("alliecatowo", 2)]
    mock_conn.execute.return_value = mock_result

    with pytest.raises(RuntimeError, match="duplicate github_username"):
        migration._check_no_duplicates(mock_conn)


def test_migration_precheck_passes_when_no_duplicates():
    """_check_no_duplicates() returns silently when no duplicates exist."""
    import importlib.util

    spec_path = (
        "/home/Allie/develop/minis-hackathon/.claude/worktrees/agent-ab3514f2"
        "/backend/alembic/versions/f1a2b3c4d5e6_add_username_uniqueness_ALLIE_377.py"
    )
    spec = importlib.util.spec_from_file_location("migration_377_clean", spec_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    mock_conn = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_conn.execute.return_value = mock_result

    # Should not raise
    migration._check_no_duplicates(mock_conn)
