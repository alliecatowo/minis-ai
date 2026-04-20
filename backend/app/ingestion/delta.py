"""Delta-query helpers for incremental ingestion (ALLIE-374 M1).

These helpers are plumbed and tested in M1 but not yet called by the pipeline.
M2 will wire them into the FETCH stage so only new/changed items are fetched.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import Evidence


async def get_latest_external_ids(
    session: AsyncSession,
    mini_id: str,
    source_type: str,
) -> set[str]:
    """Return the set of all non-NULL external_ids already stored for this source.

    M2 will use this to skip re-fetching items that are already in the corpus.

    Args:
        session: Active async SQLAlchemy session.
        mini_id: The mini whose evidence to query.
        source_type: The ingestion source name (e.g. ``"github"``).

    Returns:
        A (possibly empty) set of external_id strings.
    """
    stmt = select(Evidence.external_id).where(
        Evidence.mini_id == mini_id,
        Evidence.source_type == source_type,
        Evidence.external_id.is_not(None),
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}


async def get_max_last_fetched_at(
    session: AsyncSession,
    mini_id: str,
    source_type: str,
) -> datetime | None:
    """Return the most recent ``last_fetched_at`` timestamp for this source.

    M2 will use this as the ``since`` cursor passed to source APIs (e.g.
    GitHub's ``?since=<timestamp>`` parameter on the commits endpoint).

    NULL ``last_fetched_at`` values (legacy rows without the field populated)
    are ignored — only rows with an explicit timestamp are considered.

    Args:
        session: Active async SQLAlchemy session.
        mini_id: The mini whose evidence to query.
        source_type: The ingestion source name.

    Returns:
        The maximum timezone-aware datetime, or ``None`` if no rows have a
        non-NULL ``last_fetched_at``.
    """
    stmt = select(func.max(Evidence.last_fetched_at)).where(
        Evidence.mini_id == mini_id,
        Evidence.source_type == source_type,
        Evidence.last_fetched_at.is_not(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
