"""Persistent sliding-window rate limiting backed by the application database."""

from __future__ import annotations

import datetime
import hashlib
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.rate_limit import SlidingRateLimitEvent


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after: int | None = None


class SlidingRateLimitStore(Protocol):
    async def hit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
        *,
        now: datetime.datetime | None = None,
    ) -> RateLimitDecision: ...


def rate_limit_key_hash(key: str) -> str:
    """Hash bucket keys so raw IPs/tokens are not persisted."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _lock_id_for_key(key_hash: str) -> int:
    """Return a signed 64-bit advisory-lock id derived from the key hash."""
    return int.from_bytes(bytes.fromhex(key_hash[:16]), byteorder="big", signed=True)


class DatabaseSlidingWindowRateLimitStore:
    """Database-backed sliding-window limiter shared by all app instances."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def hit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int,
        *,
        now: datetime.datetime | None = None,
    ) -> RateLimitDecision:
        now = now or datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(seconds=window_seconds)
        key_hash = rate_limit_key_hash(key)

        async with self._session_factory() as session:
            async with session.begin():
                await self._lock_key_if_supported(session, key_hash)

                await session.execute(
                    delete(SlidingRateLimitEvent).where(
                        SlidingRateLimitEvent.key_hash == key_hash,
                        SlidingRateLimitEvent.created_at < cutoff,
                    )
                )

                count_result = await session.execute(
                    select(func.count())
                    .select_from(SlidingRateLimitEvent)
                    .where(
                        SlidingRateLimitEvent.key_hash == key_hash,
                        SlidingRateLimitEvent.created_at >= cutoff,
                    )
                )
                count = count_result.scalar_one()

                if count >= max_requests:
                    oldest_result = await session.execute(
                        select(SlidingRateLimitEvent.created_at)
                        .where(
                            SlidingRateLimitEvent.key_hash == key_hash,
                            SlidingRateLimitEvent.created_at >= cutoff,
                        )
                        .order_by(SlidingRateLimitEvent.created_at.asc())
                        .limit(1)
                    )
                    oldest = oldest_result.scalar_one_or_none() or now
                    if oldest.tzinfo is None:
                        oldest = oldest.replace(tzinfo=datetime.timezone.utc)
                    retry_after = max(1, int(window_seconds - (now - oldest).total_seconds()))
                    return RateLimitDecision(allowed=False, retry_after=retry_after)

                session.add(SlidingRateLimitEvent(key_hash=key_hash, created_at=now))
                return RateLimitDecision(allowed=True)

    async def _lock_key_if_supported(self, session: AsyncSession, key_hash: str) -> None:
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return

        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": _lock_id_for_key(key_hash)},
        )


_default_store: DatabaseSlidingWindowRateLimitStore | None = None


def get_default_rate_limit_store() -> DatabaseSlidingWindowRateLimitStore:
    global _default_store
    if _default_store is None:
        from app.db import async_session

        _default_store = DatabaseSlidingWindowRateLimitStore(async_session)
    return _default_store
