"""Shared fixtures for backend tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.synthesis.explorers.base import ExplorerReport, MemoryEntry


_REAL_RATE_LIMIT_TEST_FILES = {
    "test_allie_405_guards.py",
    "test_allie_416_throttles.py",
    "test_persistent_rate_limit.py",
    "test_route_coverage.py",
}


@pytest.fixture(autouse=True)
def patch_persistent_rate_limit_for_route_tests(request):
    """Keep route tests independent from the migrated persistent limiter table.

    Dedicated rate-limit tests exercise the real store. Most route tests import
    the production FastAPI app directly with mocked DB sessions and do not run
    Alembic, so they should not hit persistent rate-limit storage.
    """
    if request.path.name in _REAL_RATE_LIMIT_TEST_FILES:
        yield
        return

    from app.core.persistent_rate_limit import RateLimitDecision
    from app.main import app as _app
    from app.middleware.ip_rate_limit import IPRateLimitMiddleware

    allow_store = AsyncMock()
    allow_store.hit = AsyncMock(return_value=RateLimitDecision(allowed=True))
    for middleware in _app.user_middleware:
        if middleware.cls is IPRateLimitMiddleware:
            middleware.kwargs["store"] = allow_store
    _app.middleware_stack = None

    patchers = [
        patch("app.routes.chat.check_chat_ip_mini_limit", new=AsyncMock()),
        patch("app.middleware.ip_rate_limit.check_mini_create_ip_limit", new=AsyncMock()),
        patch("app.middleware.ip_rate_limit.check_mini_sse_ip_limit", new=AsyncMock()),
    ]
    for patcher in patchers:
        patcher.start()

    yield

    for patcher in patchers:
        patcher.stop()
    _app.middleware_stack = None


# ---------------------------------------------------------------------------
# Explorer/memory helpers (used by synthesis tests)
# ---------------------------------------------------------------------------


def make_memory(
    category: str = "expertise",
    topic: str = "Python",
    content: str = "Uses Python extensively.",
    confidence: float = 0.9,
    source_type: str = "github",
    evidence_quote: str = "I love Python",
) -> MemoryEntry:
    """Factory helper for creating MemoryEntry instances."""
    return MemoryEntry(
        category=category,
        topic=topic,
        content=content,
        confidence=confidence,
        source_type=source_type,
        evidence_quote=evidence_quote,
    )


def make_report(
    source_name: str = "github",
    personality_findings: str = "",
    memory_entries: list[MemoryEntry] | None = None,
    behavioral_quotes: list[dict] | None = None,
) -> ExplorerReport:
    """Factory helper for creating ExplorerReport instances."""
    return ExplorerReport(
        source_name=source_name,
        personality_findings=personality_findings,
        memory_entries=memory_entries or [],
        behavioral_quotes=behavioral_quotes or [],
    )


# ---------------------------------------------------------------------------
# App / client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    """Return the FastAPI application instance."""
    from app.main import app as _app

    yield _app

    # Clean up dependency overrides after each test
    _app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    """Return an httpx.AsyncClient configured to talk to the test app via ASGI.

    Overrides DB session and optional-user auth to avoid real connections.
    """
    from httpx import ASGITransport, AsyncClient
    from app.core.auth import get_optional_user
    from app.db import get_session

    # Provide a no-op mock session so all routes that hit the DB don't crash
    session = MagicMock()
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

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_optional_user] = lambda: None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_user():
    """Return a mock User object suitable for auth dependency overrides."""
    user = MagicMock()
    user.id = str(uuid.uuid4())
    user.github_username = "testuser"
    user.display_name = "Test User"
    user.avatar_url = None
    return user


@pytest.fixture
def mock_pydantic_ai_agent():
    """Patch pydantic_ai.Agent so no real LLM calls are made.

    Yields the mock Agent class. Use in tests that import Agent via llm.py or agent.py.
    """
    mock_result = MagicMock()
    mock_result.output = "Mocked LLM response"
    mock_result.usage.return_value = MagicMock(input_tokens=10, output_tokens=20)

    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_result)
    mock_agent_instance.run_stream = MagicMock()

    mock_agent_class = MagicMock(return_value=mock_agent_instance)

    with patch("pydantic_ai.Agent", mock_agent_class):
        yield mock_agent_class
