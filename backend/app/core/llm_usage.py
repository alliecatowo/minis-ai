"""LLM usage observability helpers (ALLIE-405).

Responsibilities:
- Emit a structured log line on every LLM call.
- Upsert daily aggregated counters into ``llm_usage_daily``.
- Provide ``get_last_24h_totals()`` consumed by the admin endpoint.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)


def log_llm_call(
    *,
    tier: str,
    tokens_in: int,
    tokens_out: int,
    user_id: str | None = None,
    mini_id: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
) -> None:
    """Emit a structured log line for every LLM call.

    This is intentionally sync / fire-and-forget so it cannot block the
    agent loop. The async DB upsert is handled separately by
    ``record_llm_call_async()``.
    """
    logger.info(
        "llm.usage tier=%s tokens_in=%d tokens_out=%d total=%d user_id=%s mini_id=%s "
        "endpoint=%s model=%s",
        tier,
        tokens_in,
        tokens_out,
        tokens_in + tokens_out,
        user_id or "anonymous",
        mini_id or "-",
        endpoint or "-",
        model or "-",
    )


async def record_llm_call_async(
    *,
    tier: str,
    tokens_in: int,
    tokens_out: int,
    user_id: str | None = None,
    endpoint: str | None = None,
    session_factory: Any = None,
) -> None:
    """Upsert daily aggregated counters.

    If ``session_factory`` is None the function is a no-op (e.g. in tests
    that don't wire up a DB).
    """
    if session_factory is None:
        return

    today = datetime.date.today()
    # Normalise user_id — cap at 255 chars to match column size
    uid = (user_id or "anonymous")[:255]
    ep = (endpoint or "unknown")[:255]

    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from app.models.usage import LLMUsageDaily

        async with session_factory() as session:
            async with session.begin():
                # Try an upsert via INSERT … ON CONFLICT DO UPDATE (PostgreSQL)
                stmt = (
                    pg_insert(LLMUsageDaily)
                    .values(
                        day=today,
                        model_tier=tier,
                        user_id=uid,
                        endpoint=ep,
                        call_count=1,
                        input_tokens=tokens_in,
                        output_tokens=tokens_out,
                    )
                    .on_conflict_do_update(
                        constraint="uq_llm_usage_daily",
                        set_={
                            "call_count": LLMUsageDaily.call_count + 1,
                            "input_tokens": LLMUsageDaily.input_tokens + tokens_in,
                            "output_tokens": LLMUsageDaily.output_tokens + tokens_out,
                        },
                    )
                )
                await session.execute(stmt)
    except Exception:
        # Never let observability failures break the caller
        logger.warning("llm_usage_daily upsert failed", exc_info=True)


async def get_last_24h_totals(session_factory: Any) -> list[dict]:
    """Return per-(tier, user_id, endpoint) totals for the last 24 hours.

    Used by the admin endpoint ``GET /api/admin/llm-usage``.
    """
    since = datetime.date.today() - datetime.timedelta(days=1)

    try:
        from sqlalchemy import select

        from app.models.usage import LLMUsageDaily

        async with session_factory() as session:
            rows = await session.execute(select(LLMUsageDaily).where(LLMUsageDaily.day >= since))
            return [
                {
                    "day": str(r.day),
                    "model_tier": r.model_tier,
                    "user_id": r.user_id,
                    "endpoint": r.endpoint,
                    "call_count": r.call_count,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                }
                for r in rows.scalars().all()
            ]
    except Exception:
        logger.warning("get_last_24h_totals failed", exc_info=True)
        return []
