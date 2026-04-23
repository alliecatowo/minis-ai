"""Review outcomes ingestion source plugin."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import ReviewCycle
from app.plugins.base import EvidenceItem, IngestionSource

logger = logging.getLogger(__name__)


def _extract_approval_state(review_state: dict | None) -> str | None:
    """Read the approval state from a structured review-state payload."""
    if not isinstance(review_state, dict):
        return None

    expressed_feedback = review_state.get("expressed_feedback")
    if not isinstance(expressed_feedback, dict):
        return None

    approval_state = expressed_feedback.get("approval_state")
    return approval_state if isinstance(approval_state, str) else None


def _extract_feedback_summary(review_state: dict | None) -> str | None:
    """Read the human-facing summary from a structured review-state payload."""
    if not isinstance(review_state, dict):
        return None

    expressed_feedback = review_state.get("expressed_feedback")
    if not isinstance(expressed_feedback, dict):
        return None

    summary = expressed_feedback.get("summary")
    if not isinstance(summary, str):
        return None

    summary = summary.strip()
    return summary or None


class ReviewOutcomesSource(IngestionSource):
    """Ingestion source that pulls ReviewCycle outcomes for a mini."""

    name = "review_outcomes"

    async def fetch_items(
        self,
        identifier: str,
        mini_id: str,
        session: AsyncSession | None,
        *,
        since_external_ids: set[str] | None = None,
    ) -> AsyncIterator[EvidenceItem]:
        """Yield one EvidenceItem per ReviewCycle with a human outcome.

        Items whose external_id already appears in ``since_external_ids`` are skipped.
        external_id shape: ``review_outcome:{review_cycle_id}``
        """
        if session is None:
            return

        since = since_external_ids or set()

        stmt = select(ReviewCycle).where(
            ReviewCycle.mini_id == mini_id,
            ReviewCycle.human_review_outcome.is_not(None),
        )
        result = await session.execute(stmt)
        cycles = result.scalars().all()

        for cycle in cycles:
            external_id = f"review_outcome:{cycle.id}"
            if external_id in since:
                continue

            predicted_approval = _extract_approval_state(cycle.predicted_state) or "unknown"
            actual_approval = _extract_approval_state(cycle.human_review_outcome) or "unknown"
            
            human_summary = _extract_feedback_summary(cycle.human_review_outcome) or "N/A"
            delta = cycle.delta_metrics or {}

            # Format the content to highlight the DELTA
            content = (
                f"Predicted Approval: {predicted_approval}\n"
                f"Human did: {actual_approval}\n"
                f"Human Summary: {human_summary}\n"
                f"Delta: {delta}"
            )

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="review_outcome",
                content=content,
                context="code_review",
                evidence_date=cycle.human_reviewed_at or cycle.updated_at,
                metadata={
                    "review_cycle_id": cycle.id,
                    "source_external_id": cycle.external_id,
                    "source_type": cycle.source_type,
                },
                privacy="public",
            )
