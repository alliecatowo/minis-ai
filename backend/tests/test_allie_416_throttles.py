"""Tests for ALLIE-416: per-IP throttle on mini creation + progress SSE."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException


def _make_user(github_username: str | None = None, display_name: str | None = None):
    return SimpleNamespace(github_username=github_username, display_name=display_name)


@pytest_asyncio.fixture
async def rate_limit_store():
    """SQLite-backed persistent limiter for tests."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.core.persistent_rate_limit import DatabaseSlidingWindowRateLimitStore
    from app.models.rate_limit import SlidingRateLimitEvent

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SlidingRateLimitEvent.__table__.create)

    yield DatabaseSlidingWindowRateLimitStore(
        async_sessionmaker(engine, expire_on_commit=False)
    )

    await engine.dispose()


class TestMiniCreateIpThrottle:
    """Tests for check_mini_create_ip_limit()."""

    @pytest.mark.asyncio
    async def test_first_request_allowed(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 2

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
            patch("app.core.admin.settings") as mock_rl,
        ):
            mock_rl.admin_username_list = ["alliecatowo"]
            await check_mini_create_ip_limit(
                "10.0.0.1",
                user=_make_user(github_username="regulardev"),
                store=rate_limit_store,
            )

    @pytest.mark.asyncio
    async def test_third_request_returns_429(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 2
        non_admin = _make_user(github_username="regulardev")

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
            patch("app.core.admin.settings") as mock_rl,
        ):
            mock_rl.admin_username_list = ["alliecatowo"]
            await check_mini_create_ip_limit("10.0.0.2", user=non_admin, store=rate_limit_store)
            await check_mini_create_ip_limit("10.0.0.2", user=non_admin, store=rate_limit_store)

            with pytest.raises(HTTPException) as exc_info:
                await check_mini_create_ip_limit(
                    "10.0.0.2",
                    user=non_admin,
                    store=rate_limit_store,
                )

        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers

    @pytest.mark.asyncio
    async def test_retry_after_header_is_positive(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 1
        non_admin = _make_user(github_username="regulardev")

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
            patch("app.core.admin.settings") as mock_rl,
        ):
            mock_rl.admin_username_list = ["alliecatowo"]
            await check_mini_create_ip_limit("10.0.0.3", user=non_admin, store=rate_limit_store)

            with pytest.raises(HTTPException) as exc_info:
                await check_mini_create_ip_limit(
                    "10.0.0.3",
                    user=non_admin,
                    store=rate_limit_store,
                )

        assert int(exc_info.value.headers["Retry-After"]) >= 1

    @pytest.mark.asyncio
    async def test_admin_bypasses_create_throttle(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 1

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
            patch("app.core.admin.settings") as mock_rl,
        ):
            mock_rl.admin_username_list = ["alliecatowo"]
            await check_mini_create_ip_limit(
                "10.0.0.4",
                user=_make_user(github_username="alliecatowo"),
                store=rate_limit_store,
            )

    @pytest.mark.asyncio
    async def test_different_ips_have_independent_windows(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 2
        non_admin = _make_user(github_username="regulardev")

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
            patch("app.core.admin.settings") as mock_rl,
        ):
            mock_rl.admin_username_list = ["alliecatowo"]
            await check_mini_create_ip_limit("10.0.1.1", user=non_admin, store=rate_limit_store)
            await check_mini_create_ip_limit("10.0.1.1", user=non_admin, store=rate_limit_store)
            await check_mini_create_ip_limit("10.0.1.2", user=non_admin, store=rate_limit_store)

    @pytest.mark.asyncio
    async def test_create_key_does_not_collide_with_chat_key(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 2

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
            patch("app.core.admin.settings") as mock_rl,
        ):
            mock_rl.admin_username_list = ["alliecatowo"]
            await check_mini_create_ip_limit(
                "10.0.0.5",
                user=_make_user(github_username="regulardev"),
                store=rate_limit_store,
            )


class TestMiniSseIpThrottle:
    """Tests for check_mini_sse_ip_limit()."""

    @pytest.mark.asyncio
    async def test_first_connection_allowed(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_sse_ip_per_min_limit = 10

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
        ):
            await check_mini_sse_ip_limit("192.168.1.1", store=rate_limit_store)

    @pytest.mark.asyncio
    async def test_eleventh_connection_returns_429(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_sse_ip_per_min_limit = 10
        ip = "192.168.1.2"

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
        ):
            for _ in range(10):
                await check_mini_sse_ip_limit(ip, store=rate_limit_store)

            with pytest.raises(HTTPException) as exc_info:
                await check_mini_sse_ip_limit(ip, store=rate_limit_store)

        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers

    @pytest.mark.asyncio
    async def test_sse_retry_after_header_is_positive(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_sse_ip_per_min_limit = 3
        ip = "192.168.1.3"

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
        ):
            for _ in range(3):
                await check_mini_sse_ip_limit(ip, store=rate_limit_store)
            with pytest.raises(HTTPException) as exc_info:
                await check_mini_sse_ip_limit(ip, store=rate_limit_store)

        assert int(exc_info.value.headers["Retry-After"]) >= 1

    @pytest.mark.asyncio
    async def test_sse_different_ips_are_independent(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_sse_ip_per_min_limit = 2
        ip_a = "192.168.2.1"
        ip_b = "192.168.2.2"

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
        ):
            for _ in range(2):
                await check_mini_sse_ip_limit(ip_a, store=rate_limit_store)
            with pytest.raises(HTTPException) as exc_info:
                await check_mini_sse_ip_limit(ip_a, store=rate_limit_store)
            await check_mini_sse_ip_limit(ip_b, store=rate_limit_store)

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_sse_key_does_not_collide_with_create_or_chat(self, rate_limit_store):
        from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_sse_ip_per_min_limit = 10

        with (
            patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True),
            patch("app.core.config.settings", mock_settings),
        ):
            await check_mini_sse_ip_limit("192.168.1.4", store=rate_limit_store)


class TestAllie416Settings:
    def test_mini_create_ip_hourly_limit_default(self):
        from app.core.config import Settings

        s = Settings()
        assert s.mini_create_ip_hourly_limit == 2

    def test_mini_sse_ip_per_min_limit_default(self):
        from app.core.config import Settings

        s = Settings()
        assert s.mini_sse_ip_per_min_limit == 10

    def test_mini_create_ip_hourly_limit_env_override(self):
        from app.core.config import Settings

        s = Settings(mini_create_ip_hourly_limit=5)
        assert s.mini_create_ip_hourly_limit == 5

    def test_mini_sse_ip_per_min_limit_env_override(self):
        from app.core.config import Settings

        s = Settings(mini_sse_ip_per_min_limit=20)
        assert s.mini_sse_ip_per_min_limit == 20
