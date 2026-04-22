"""Persistence helpers for review prediction/outcome cycles."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import ReviewCycle
from app.models.schemas import (
    ReviewCycleOutcomeUpdateRequest,
    ReviewCyclePredictionUpsertRequest,
)


def _extract_approval_state(review_state: dict | None) -> str | None:
    """Read the approval state from a structured review-state payload."""
    if not isinstance(review_state, dict):
        return None

    expressed_feedback = review_state.get("expressed_feedback")
    if not isinstance(expressed_feedback, dict):
        return None

    approval_state = expressed_feedback.get("approval_state")
    return approval_state if isinstance(approval_state, str) else None


async def upsert_review_cycle_prediction(
    session: AsyncSession,
    mini_id: str,
    body: ReviewCyclePredictionUpsertRequest,
) -> ReviewCycle:
    """Create or refresh the predicted state for one review cycle."""
    result = await session.execute(
        select(ReviewCycle).where(
            ReviewCycle.mini_id == mini_id,
            ReviewCycle.source_type == body.source_type,
            ReviewCycle.external_id == body.external_id,
        )
    )
    cycle = result.scalar_one_or_none()
    predicted_at = datetime.now(UTC)
    predicted_state = body.predicted_state.model_dump(mode="json")

    if cycle is None:
        cycle = ReviewCycle(
            mini_id=mini_id,
            source_type=body.source_type,
            external_id=body.external_id,
            metadata_json=body.metadata_json,
            predicted_state=predicted_state,
            predicted_at=predicted_at,
        )
        session.add(cycle)
    else:
        cycle.source_type = body.source_type
        cycle.predicted_state = predicted_state
        cycle.predicted_at = predicted_at
        if body.metadata_json is not None:
            cycle.metadata_json = body.metadata_json

    await session.commit()
    await session.refresh(cycle)
    return cycle


async def finalize_review_cycle(
    session: AsyncSession,
    mini_id: str,
    body: ReviewCycleOutcomeUpdateRequest,
) -> ReviewCycle | None:
    """Persist the eventual human review outcome and compact delta metrics."""
    result = await session.execute(
        select(ReviewCycle).where(
            ReviewCycle.mini_id == mini_id,
            ReviewCycle.source_type == body.source_type,
            ReviewCycle.external_id == body.external_id,
        )
    )
    cycle = result.scalar_one_or_none()
    if cycle is None:
        return None

    human_review_outcome = body.human_review_outcome.model_dump(mode="json")
    predicted_approval_state = _extract_approval_state(cycle.predicted_state)
    actual_approval_state = _extract_approval_state(human_review_outcome)

    delta_metrics = dict(body.delta_metrics)
    if predicted_approval_state is not None:
        delta_metrics["predicted_approval_state"] = predicted_approval_state
    if actual_approval_state is not None:
        delta_metrics["actual_approval_state"] = actual_approval_state
    if predicted_approval_state is not None and actual_approval_state is not None:
        delta_metrics["approval_state_changed"] = (
            predicted_approval_state != actual_approval_state
        )

    cycle.human_review_outcome = human_review_outcome
    cycle.delta_metrics = delta_metrics
    cycle.human_reviewed_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(cycle)
    return cycle
