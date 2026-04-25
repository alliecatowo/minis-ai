"""Persistence helpers for artifact-review (design_doc / issue_plan) prediction/outcome cycles.

Mirrors review_cycles.py structure for non-PR artifact types. The key differences:

- predicted_state stores an ArtifactReviewV1 blob (not StructuredReviewState).
- human_outcome stores an ArtifactReviewOutcomeCaptureV1 blob (not StructuredReviewState).
- delta_metrics are derived from suggestion_outcomes instead of PR issue reconciliation.
- Evidence writeback uses source_type "artifact_review_writeback" to distinguish
  from the existing "review_writeback" source.
- Framework confidence deltas are fed via the same apply_review_outcome_deltas() call
  used by PR cycles, mapped from suggestion_outcomes to a compatible issue_outcomes shape.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import ArtifactReviewCycle, ExplorerFinding, ExplorerQuote
from app.models.schemas import (
    ArtifactReviewCycleOutcomeUpdateRequest,
    ArtifactReviewCyclePredictionUpsertRequest,
)

logger = logging.getLogger(__name__)

_ARTIFACT_REVIEW_WRITEBACK_SOURCE = "artifact_review_writeback"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or None


def _artifact_cycle_marker(cycle: ArtifactReviewCycle) -> str:
    """Return a stable marker used to replace prior writeback artifacts."""
    return f"[artifact_review_cycle:{cycle.id}]"


def _artifact_cycle_target(cycle: ArtifactReviewCycle) -> str:
    """Build a compact label for the reviewed artifact."""
    metadata_json = cycle.metadata_json if isinstance(cycle.metadata_json, dict) else {}
    title = metadata_json.get("title")
    if isinstance(title, str) and title.strip():
        return f"{cycle.artifact_type}:{title.strip()[:80]}"
    return f"{cycle.artifact_type}:{cycle.external_id}"


def _extract_expressed_feedback_summary(predicted_state: dict | None) -> str | None:
    """Pull the top-level expressed_feedback.summary from a predicted ArtifactReviewV1 blob."""
    if not isinstance(predicted_state, dict):
        return None
    ef = predicted_state.get("expressed_feedback")
    if not isinstance(ef, dict):
        return None
    summary = ef.get("summary")
    if isinstance(summary, str):
        summary = summary.strip()
        return summary or None
    return None


def _extract_predicted_approval_state(predicted_state: dict | None) -> str | None:
    if not isinstance(predicted_state, dict):
        return None
    ef = predicted_state.get("expressed_feedback")
    if not isinstance(ef, dict):
        return None
    val = ef.get("approval_state")
    return _normalize_value(val)


def _build_suggestion_issue_outcomes(
    human_outcome: dict | None,
) -> list[dict[str, Any]]:
    """Convert suggestion_outcomes → issue_outcomes shape compatible with apply_review_outcome_deltas."""
    if not isinstance(human_outcome, dict):
        return []
    suggestion_outcomes = human_outcome.get("suggestion_outcomes")
    if not isinstance(suggestion_outcomes, list):
        return []

    issue_outcomes: list[dict[str, Any]] = []
    for item in suggestion_outcomes:
        if not isinstance(item, dict):
            continue
        suggestion_key = item.get("suggestion_key")
        if not isinstance(suggestion_key, str) or not suggestion_key.strip():
            continue
        outcome_val = _normalize_value(item.get("outcome"))
        # Map artifact outcomes → reconciler outcome vocabulary
        mapped_outcome = _map_artifact_outcome(outcome_val)
        issue_outcomes.append(
            {
                "issue_key": suggestion_key.strip(),
                "outcome": mapped_outcome,
                "predicted_type": "note",  # artifact suggestions are non-blocking by default
                "predicted_disposition": "comment",
                "predicted_summary": item.get("summary"),
                "actual_type": None,
                "actual_disposition": None,
                "actual_summary": item.get("summary"),
            }
        )
    return issue_outcomes


def _map_artifact_outcome(outcome: str | None) -> str:
    """Map ArtifactReviewOutcomeValueV1 → reconciler outcome vocabulary.

    Mapping rationale:
    - "accepted"  → "confirmed"   (prediction was right, outcome adopted)
    - "revised"   → "downgraded"  (partial adoption, less severe than predicted)
    - "rejected"  → "escalated"   (reviewer disagreed, higher severity)
    - "deferred"  → "not_raised"  (not addressed this cycle)
    """
    mapping = {
        "accepted": "confirmed",
        "revised": "downgraded",
        "rejected": "escalated",
        "deferred": "not_raised",
    }
    return mapping.get(outcome or "", "not_raised")


def _build_suggestion_outcome_counts(human_outcome: dict | None) -> dict[str, int]:
    if not isinstance(human_outcome, dict):
        return {}
    suggestion_outcomes = human_outcome.get("suggestion_outcomes")
    if not isinstance(suggestion_outcomes, list):
        return {}
    counts: dict[str, int] = {}
    for item in suggestion_outcomes:
        if not isinstance(item, dict):
            continue
        outcome_val = _normalize_value(item.get("outcome"))
        if outcome_val:
            counts[outcome_val] = counts.get(outcome_val, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Evidence writeback
# ---------------------------------------------------------------------------


async def _writeback_artifact_review_cycle_learning(
    session: AsyncSession,
    cycle: ArtifactReviewCycle,
) -> None:
    """Persist compact artifact-review outcome artifacts for downstream synthesis."""
    marker = _artifact_cycle_marker(cycle)
    marker_prefix = f"{marker}%"

    await session.execute(
        delete(ExplorerFinding).where(
            ExplorerFinding.mini_id == cycle.mini_id,
            ExplorerFinding.source_type == _ARTIFACT_REVIEW_WRITEBACK_SOURCE,
            ExplorerFinding.content.like(marker_prefix),
        )
    )
    await session.execute(
        delete(ExplorerQuote).where(
            ExplorerQuote.mini_id == cycle.mini_id,
            ExplorerQuote.source_type == _ARTIFACT_REVIEW_WRITEBACK_SOURCE,
            ExplorerQuote.context.like(marker_prefix),
        )
    )

    target = _artifact_cycle_target(cycle)
    predicted_approval_state = _extract_predicted_approval_state(cycle.predicted_state) or "unknown"
    human_outcome = cycle.human_outcome if isinstance(cycle.human_outcome, dict) else {}
    artifact_outcome = _normalize_value(human_outcome.get("artifact_outcome")) or "unknown"
    final_disposition = _normalize_value(human_outcome.get("final_disposition")) or "unknown"
    reviewer_summary = human_outcome.get("reviewer_summary")
    if isinstance(reviewer_summary, str):
        reviewer_summary = reviewer_summary.strip() or None

    finding_content = (
        f"{marker} Artifact review outcome calibration for {target}: "
        f"predicted approval_state={predicted_approval_state}, "
        f"artifact_outcome={artifact_outcome}, "
        f"final_disposition={final_disposition}."
    )

    if isinstance(cycle.delta_metrics, dict):
        suggestion_outcome_counts = cycle.delta_metrics.get("suggestion_outcome_counts")
        if isinstance(suggestion_outcome_counts, dict) and suggestion_outcome_counts:
            counts_str = ", ".join(
                f"{k}={v}" for k, v in sorted(suggestion_outcome_counts.items())
            )
            finding_content += f" suggestion_outcomes={counts_str}."

        issue_outcomes = cycle.delta_metrics.get("issue_outcomes")
        if isinstance(issue_outcomes, list) and issue_outcomes:
            rendered = [
                f"{item['issue_key']}={item['outcome']}"
                for item in issue_outcomes
                if isinstance(item, dict) and item.get("issue_key") and item.get("outcome")
            ]
            if rendered:
                finding_content += f" issue_outcomes={', '.join(rendered)}."

    if reviewer_summary:
        finding_content += f" Reviewer summary: {reviewer_summary}"

    session.add(
        ExplorerFinding(
            mini_id=cycle.mini_id,
            source_type=_ARTIFACT_REVIEW_WRITEBACK_SOURCE,
            category="decision_patterns",
            content=finding_content,
            confidence=0.95,
        )
    )

    if reviewer_summary:
        session.add(
            ExplorerQuote(
                mini_id=cycle.mini_id,
                source_type=_ARTIFACT_REVIEW_WRITEBACK_SOURCE,
                quote=reviewer_summary,
                context=f"{marker} human_outcome for {target}",
                significance="artifact_review_outcome",
            )
        )

    await _apply_artifact_framework_confidence_deltas(session, cycle)


async def _apply_artifact_framework_confidence_deltas(
    session: AsyncSession,
    cycle: ArtifactReviewCycle,
) -> None:
    """Feed suggestion_outcomes (mapped to issue_outcomes) into framework confidence scores."""
    import json as _json

    from sqlalchemy import text as _text

    from app.synthesis.decision_frameworks import (
        DRIFT_ALERT_THRESHOLD,
        apply_review_outcome_deltas,
        detect_band_change,
    )

    issue_outcomes = None
    if isinstance(cycle.delta_metrics, dict):
        issue_outcomes = cycle.delta_metrics.get("issue_outcomes")
    if not isinstance(issue_outcomes, list) or not issue_outcomes:
        return

    row = await session.execute(
        _text("SELECT principles_json FROM minis WHERE id = :id"),
        {"id": cycle.mini_id},
    )
    record = row.fetchone()
    if record is None:
        return

    raw_pj = record[0]
    if raw_pj is None:
        return
    principles_json = raw_pj if isinstance(raw_pj, dict) else _json.loads(raw_pj)
    if not isinstance(principles_json, dict):
        return

    updated_principles, updates = apply_review_outcome_deltas(
        principles_json=principles_json,
        cycle_id=cycle.id,
        issue_outcomes=issue_outcomes,
    )

    if updates:
        await session.execute(
            _text("UPDATE minis SET principles_json = :pj WHERE id = :id"),
            {"pj": _json.dumps(updated_principles), "id": cycle.mini_id},
        )
        logger.info(
            "artifact_framework_confidence_delta mini_id=%s cycle_id=%s updates=%d",
            cycle.mini_id,
            cycle.id,
            len(updates),
        )
        for delta in updates:
            shift = abs(delta.new_confidence - delta.prior_confidence)
            band_change = detect_band_change(delta.prior_confidence, delta.new_confidence)
            band_change_str = f"{band_change[0]}->{band_change[1]}" if band_change else None
            if band_change is not None or shift >= DRIFT_ALERT_THRESHOLD:
                logger.info(
                    "framework_drift_alert",
                    extra={
                        "mini_id": str(cycle.mini_id),
                        "framework_id": delta.framework_id,
                        "previous_confidence": delta.prior_confidence,
                        "new_confidence": delta.new_confidence,
                        "band_change": band_change_str,
                        "shift_magnitude": shift,
                        "delta_reason": delta.outcome_type,
                        "source": "artifact_review_writeback",
                    },
                )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def upsert_artifact_review_prediction(
    session: AsyncSession,
    mini_id: str,
    body: ArtifactReviewCyclePredictionUpsertRequest,
) -> ArtifactReviewCycle:
    """Create or refresh the predicted state for one artifact-review cycle."""
    result = await session.execute(
        select(ArtifactReviewCycle).where(
            ArtifactReviewCycle.mini_id == mini_id,
            ArtifactReviewCycle.artifact_type == body.artifact_type,
            ArtifactReviewCycle.external_id == body.external_id,
        )
    )
    cycle = result.scalar_one_or_none()
    predicted_at = datetime.now(UTC)
    predicted_state = body.predicted_state.model_dump(mode="json")

    if cycle is None:
        cycle = ArtifactReviewCycle(
            mini_id=mini_id,
            artifact_type=body.artifact_type,
            external_id=body.external_id,
            metadata_json=body.metadata_json,
            predicted_state=predicted_state,
            predicted_at=predicted_at,
        )
        session.add(cycle)
    else:
        cycle.predicted_state = predicted_state
        cycle.predicted_at = predicted_at
        if body.metadata_json is not None:
            cycle.metadata_json = body.metadata_json

    await session.commit()
    await session.refresh(cycle)
    return cycle


async def finalize_artifact_review_outcome(
    session: AsyncSession,
    mini_id: str,
    body: ArtifactReviewCycleOutcomeUpdateRequest,
) -> ArtifactReviewCycle | None:
    """Persist the eventual human artifact-review outcome and compact delta metrics."""
    result = await session.execute(
        select(ArtifactReviewCycle).where(
            ArtifactReviewCycle.mini_id == mini_id,
            ArtifactReviewCycle.artifact_type == body.artifact_type,
            ArtifactReviewCycle.external_id == body.external_id,
        )
    )
    cycle = result.scalar_one_or_none()
    if cycle is None:
        return None

    human_outcome = body.human_outcome.model_dump(mode="json")

    # Build delta_metrics from suggestion_outcomes + outcome value
    delta_metrics: dict[str, Any] = {}
    artifact_outcome = _normalize_value(human_outcome.get("artifact_outcome"))
    if artifact_outcome:
        delta_metrics["artifact_outcome"] = artifact_outcome
    final_disposition = _normalize_value(human_outcome.get("final_disposition"))
    if final_disposition:
        delta_metrics["final_disposition"] = final_disposition

    # Predicted approval state from stored blob
    predicted_approval_state = _extract_predicted_approval_state(cycle.predicted_state)
    if predicted_approval_state:
        delta_metrics["predicted_approval_state"] = predicted_approval_state

    # Build suggestion_outcome_counts
    suggestion_outcome_counts = _build_suggestion_outcome_counts(human_outcome)
    if suggestion_outcome_counts:
        delta_metrics["suggestion_outcome_counts"] = suggestion_outcome_counts

    # Map to issue_outcomes for framework-confidence deltas
    issue_outcomes = _build_suggestion_issue_outcomes(human_outcome)
    if issue_outcomes:
        delta_metrics["issue_outcomes"] = issue_outcomes
        delta_metrics["suggestion_count"] = len(issue_outcomes)

    cycle.human_outcome = human_outcome
    cycle.delta_metrics = delta_metrics
    cycle.finalized_at = datetime.now(UTC)
    await _writeback_artifact_review_cycle_learning(session, cycle)

    await session.commit()
    await session.refresh(cycle)
    return cycle
