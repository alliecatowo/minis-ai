"""Persistence helpers for review prediction/outcome cycles."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import ExplorerFinding, ExplorerQuote, ReviewCycle
from app.models.schemas import (
    ReviewCycleOutcomeUpdateRequest,
    ReviewCyclePredictionUpsertRequest,
)

_REVIEW_WRITEBACK_SOURCE = "review_writeback"


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


def _review_cycle_marker(cycle: ReviewCycle) -> str:
    """Return a stable marker used to replace prior writeback artifacts."""
    return f"[review_cycle:{cycle.id}]"


def _review_cycle_target(cycle: ReviewCycle) -> str:
    """Build a compact label for the reviewed artifact."""
    metadata_json = cycle.metadata_json if isinstance(cycle.metadata_json, dict) else {}
    repo_full_name = metadata_json.get("repo_full_name")
    pr_number = metadata_json.get("pr_number")

    if isinstance(repo_full_name, str) and repo_full_name.strip():
        if pr_number is not None:
            return f"{repo_full_name}#{pr_number}"
        return repo_full_name
    return cycle.external_id


async def _writeback_review_cycle_learning(
    session: AsyncSession,
    cycle: ReviewCycle,
) -> None:
    """Persist compact review-outcome artifacts for downstream synthesis."""
    marker = _review_cycle_marker(cycle)
    marker_prefix = f"{marker}%"

    await session.execute(
        delete(ExplorerFinding).where(
            ExplorerFinding.mini_id == cycle.mini_id,
            ExplorerFinding.source_type == _REVIEW_WRITEBACK_SOURCE,
            ExplorerFinding.content.like(marker_prefix),
        )
    )
    await session.execute(
        delete(ExplorerQuote).where(
            ExplorerQuote.mini_id == cycle.mini_id,
            ExplorerQuote.source_type == _REVIEW_WRITEBACK_SOURCE,
            ExplorerQuote.context.like(marker_prefix),
        )
    )

    predicted_approval_state = _extract_approval_state(cycle.predicted_state) or "unknown"
    actual_approval_state = _extract_approval_state(cycle.human_review_outcome) or "unknown"

    approval_state_changed = None
    if isinstance(cycle.delta_metrics, dict):
        changed_value = cycle.delta_metrics.get("approval_state_changed")
        if isinstance(changed_value, bool):
            approval_state_changed = changed_value
    if approval_state_changed is None:
        approval_state_changed = predicted_approval_state != actual_approval_state

    target = _review_cycle_target(cycle)
    feedback_summary = _extract_feedback_summary(cycle.human_review_outcome)
    finding_content = (
        f"{marker} Review outcome calibration for {target}: "
        f"predicted approval_state={predicted_approval_state}, "
        f"actual approval_state={actual_approval_state}, "
        f"approval_state_changed={'yes' if approval_state_changed else 'no'}."
    )
    if feedback_summary:
        finding_content += f" Human summary: {feedback_summary}"

    session.add(
        ExplorerFinding(
            mini_id=cycle.mini_id,
            source_type=_REVIEW_WRITEBACK_SOURCE,
            category="decision_patterns",
            content=finding_content,
            confidence=0.95,
        )
    )

    if feedback_summary:
        session.add(
            ExplorerQuote(
                mini_id=cycle.mini_id,
                source_type=_REVIEW_WRITEBACK_SOURCE,
                quote=feedback_summary,
                context=f"{marker} human_review_outcome for {target}",
                significance="review_outcome",
            )
        )


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
    await _writeback_review_cycle_learning(session, cycle)

    await session.commit()
    await session.refresh(cycle)
    return cycle
