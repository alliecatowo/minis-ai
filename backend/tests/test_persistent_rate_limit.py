"""Tests for MINI-120 persistent/shared rate-limit storage."""

from __future__ import annotations

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_sliding_window_state_is_shared_across_store_instances():
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

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    store_a = DatabaseSlidingWindowRateLimitStore(session_factory)
    store_b = DatabaseSlidingWindowRateLimitStore(session_factory)

    key = "chat:203.0.113.10:mini-shared:burst"
    first = await store_a.hit(key, max_requests=1, window_seconds=60)
    second = await store_b.hit(key, max_requests=1, window_seconds=60)

    await engine.dispose()

    assert first.allowed is True
    assert second.allowed is False
    assert second.retry_after is not None
    assert second.retry_after >= 1


@pytest.mark.asyncio
async def test_sliding_window_persists_hashed_keys_not_raw_ip():
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.core.persistent_rate_limit import (
        DatabaseSlidingWindowRateLimitStore,
        rate_limit_key_hash,
    )
    from app.models.rate_limit import SlidingRateLimitEvent

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SlidingRateLimitEvent.__table__.create)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    store = DatabaseSlidingWindowRateLimitStore(session_factory)
    key = "create:198.51.100.8"

    await store.hit(key, max_requests=2, window_seconds=3600)

    async with session_factory() as session:
        row = (
            await session.execute(select(SlidingRateLimitEvent).limit(1))
        ).scalar_one()

    await engine.dispose()

    assert row.key_hash == rate_limit_key_hash(key)
    assert "198.51.100.8" not in row.key_hash


@pytest.mark.asyncio
async def test_endpoint_throttle_fails_closed_when_store_unavailable():
    from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

    class FailingStore:
        async def hit(self, *args, **kwargs):
            raise RuntimeError("storage unavailable")

    with pytest.raises(HTTPException) as exc_info:
        await check_mini_sse_ip_limit("203.0.113.20", store=FailingStore())

    assert exc_info.value.status_code == 503
    assert "blocked for safety" in exc_info.value.detail
