"""Persistence helpers for review prediction/outcome cycles."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import (
    ExplorerFinding,
    ExplorerQuote,
    PredictionFeedbackMemory,
    ReviewCycle,
)
from app.models.schemas import (
    ReviewCycleOutcomeUpdateRequest,
    ReviewCyclePredictionUpsertRequest,
)

logger = logging.getLogger(__name__)

_REVIEW_WRITEBACK_SOURCE = "review_writeback"
_ARTIFACT_OUTCOME_VALUES = {"accepted", "rejected", "revised", "deferred"}
_PRIVATE_ASSESSMENT_GROUP_DEFAULTS = {
    "blocking_issues": {"type": "blocker", "disposition": "request_changes"},
    "non_blocking_issues": {"type": "note", "disposition": "comment"},
    "open_questions": {"type": "question", "disposition": "comment"},
    "positive_signals": {"type": "praise", "disposition": "approve"},
}


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


def _extract_outcome_capture(review_state: dict | None) -> dict[str, Any] | None:
    """Read structured artifact-review outcomes from a review-state payload."""
    if not isinstance(review_state, dict):
        return None

    outcome_capture = review_state.get("outcome_capture")
    return outcome_capture if isinstance(outcome_capture, dict) else None


def _extract_reviewer_summary(review_state: dict | None) -> str | None:
    """Prefer the explicit reviewer summary when outcome capture is present."""
    outcome_capture = _extract_outcome_capture(review_state)
    if isinstance(outcome_capture, dict):
        reviewer_summary = outcome_capture.get("reviewer_summary")
        if isinstance(reviewer_summary, str):
            reviewer_summary = reviewer_summary.strip()
            if reviewer_summary:
                return reviewer_summary

    return _extract_feedback_summary(review_state)


def _normalize_review_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or None


def _normalize_issue_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip().lower()
    return normalized or None


def _extract_issue_key(item: Any, *, allow_id_fallback: bool = False) -> str | None:
    if not isinstance(item, dict):
        return None

    field_names = ["issue_key", "key"]
    if allow_id_fallback:
        field_names.append("id")

    for field_name in field_names:
        issue_key = _normalize_issue_key(item.get(field_name))
        if issue_key:
            return issue_key
    return None


def _extract_issue_summary(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None

    for field_name in ("summary", "body", "detail", "value"):
        value = item.get(field_name)
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
    return None


def _extract_issue_rationale(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None

    rationale = item.get("rationale")
    if not isinstance(rationale, str):
        return None

    rationale = rationale.strip()
    return rationale or None


def _collect_suggestion_outcomes(review_state: dict | None) -> dict[str, dict[str, Any]]:
    """Collect explicit outcome-capture signals keyed by predicted suggestion/issue."""
    outcome_capture = _extract_outcome_capture(review_state)
    if not isinstance(outcome_capture, dict):
        return {}

    suggestion_outcomes = outcome_capture.get("suggestion_outcomes")
    if not isinstance(suggestion_outcomes, list):
        return {}

    outcomes: dict[str, dict[str, Any]] = {}
    for item in suggestion_outcomes:
        if not isinstance(item, dict):
            continue

        suggestion_key = _normalize_issue_key(
            item.get("suggestion_key") or item.get("issue_key") or item.get("key")
        )
        outcome = _normalize_review_value(item.get("outcome"))
        if not suggestion_key or outcome not in _ARTIFACT_OUTCOME_VALUES:
            continue

        compact_item: dict[str, Any] = {
            "suggestion_key": suggestion_key,
            "outcome": outcome,
        }
        summary = _extract_issue_summary(item)
        if summary:
            compact_item["summary"] = summary
        outcomes[suggestion_key] = compact_item

    return outcomes


def _issue_severity(
    *,
    comment_type: str | None = None,
    disposition: str | None = None,
    approval_state: str | None = None,
) -> int:
    normalized_type = _normalize_review_value(comment_type)
    normalized_disposition = _normalize_review_value(disposition)
    normalized_approval_state = _normalize_review_value(approval_state)

    if normalized_disposition == "request_changes" or normalized_type == "blocker":
        return 3
    if normalized_disposition == "comment" or normalized_type in {"note", "question"}:
        return 2
    if normalized_disposition == "approve" or normalized_type == "praise":
        return 1

    if normalized_approval_state == "request_changes":
        return 3
    if normalized_approval_state == "comment":
        return 2
    if normalized_approval_state == "approve":
        return 1
    return 0


def _merge_issue_details(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for field_name, value in override.items():
        if value is None:
            continue
        if field_name == "severity":
            merged[field_name] = max(int(merged.get(field_name) or 0), int(value))
            continue
        merged[field_name] = value
    return merged


def _collect_reconciled_issues(review_state: dict | None) -> dict[str, dict[str, Any]]:
    issues: dict[str, dict[str, Any]] = {}
    if not isinstance(review_state, dict):
        return issues

    private_assessment = review_state.get("private_assessment")
    if isinstance(private_assessment, dict):
        for group_name, defaults in _PRIVATE_ASSESSMENT_GROUP_DEFAULTS.items():
            items = private_assessment.get(group_name)
            if not isinstance(items, list):
                continue

            for item in items:
                issue_key = _extract_issue_key(item, allow_id_fallback=True)
                if not issue_key:
                    continue

                issues[issue_key] = _merge_issue_details(
                    issues.get(issue_key, {"issue_key": issue_key}),
                    {
                        "type": defaults["type"],
                        "disposition": defaults["disposition"],
                        "summary": _extract_issue_summary(item),
                        "rationale": _extract_issue_rationale(item),
                        "source": group_name,
                        "severity": _issue_severity(
                            comment_type=defaults["type"],
                            disposition=defaults["disposition"],
                        ),
                    },
                )

    expressed_feedback = review_state.get("expressed_feedback")
    if not isinstance(expressed_feedback, dict):
        return issues

    comments = expressed_feedback.get("comments")
    if not isinstance(comments, list):
        return issues

    overall_approval_state = _extract_approval_state(review_state)
    for comment in comments:
        issue_key = _extract_issue_key(comment)
        if not issue_key:
            continue

        comment_type = None
        disposition = None
        if isinstance(comment, dict):
            comment_type = _normalize_review_value(comment.get("type"))
            disposition = _normalize_review_value(comment.get("disposition"))

        issues[issue_key] = _merge_issue_details(
            issues.get(issue_key, {"issue_key": issue_key}),
            {
                "type": comment_type,
                "disposition": disposition,
                "summary": _extract_issue_summary(comment),
                "rationale": _extract_issue_rationale(comment),
                "source": "comment",
                "severity": _issue_severity(
                    comment_type=comment_type,
                    disposition=disposition,
                    approval_state=overall_approval_state,
                ),
            },
        )

    return issues


def _resolve_issue_delta(
    predicted_issue: dict[str, Any],
    actual_issue: dict[str, Any] | None,
    *,
    actual_approval_state: str | None,
    suggestion_outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if actual_issue is None and suggestion_outcome is not None:
        explicit_outcome = _normalize_review_value(suggestion_outcome.get("outcome"))
        outcome_map = {
            "accepted": ("confirmed", "accepted"),
            "revised": ("downgraded", "corrected"),
            "rejected": ("contradicted", "contradicted"),
            "deferred": ("ignored", "ignored"),
        }
        outcome, outcome_status = outcome_map.get(
            explicit_outcome or "",
            ("unknown", "unknown"),
        )
        resolved: dict[str, Any] = {
            "outcome": outcome,
            "outcome_status": outcome_status,
            "outcome_source": "outcome_capture",
            "explicit_outcome": explicit_outcome,
        }
        summary = _extract_issue_summary(suggestion_outcome)
        if summary:
            resolved["actual_summary"] = summary
        if outcome_status == "unknown":
            resolved["missing_outcome_reason"] = (
                "Outcome capture had an unrecognized suggestion outcome; no reviewer "
                "behavior was inferred."
            )
        return resolved

    predicted_severity = int(predicted_issue.get("severity") or 0)
    if actual_issue is None:
        return {
            "outcome": "unknown",
            "outcome_status": "unknown",
            "outcome_source": "missing",
            "missing_outcome_reason": (
                "Predicted issue was absent from the human review and no explicit "
                "outcome-capture signal exists; do not infer accepted, ignored, or "
                "resolved-before-review from approval_state="
                f"{actual_approval_state or 'unknown'}."
            ),
        }

    actual_severity = int(
        actual_issue.get("severity")
        or _issue_severity(approval_state=actual_approval_state)
    )

    if actual_severity > predicted_severity:
        return {
            "outcome": "escalated",
            "outcome_status": "corrected",
            "outcome_source": "human_review",
        }
    if actual_severity == predicted_severity:
        return {
            "outcome": "confirmed",
            "outcome_status": "accepted",
            "outcome_source": "human_review",
        }
    if actual_severity > 0:
        return {
            "outcome": "downgraded",
            "outcome_status": "corrected",
            "outcome_source": "human_review",
        }
    return {
        "outcome": "unknown",
        "outcome_status": "unknown",
        "outcome_source": "human_review",
        "missing_outcome_reason": "Actual issue had no severity signal; no outcome was inferred.",
    }


def _terminal_resolution(issue_outcomes: list[dict[str, Any]]) -> str | None:
    predicted_issue_outcomes = [
        item["outcome"]
        for item in issue_outcomes
        if item.get("outcome") and item.get("predicted_type") is not None
    ]
    has_missed_issue = any(item.get("outcome") == "missed" for item in issue_outcomes)

    if not predicted_issue_outcomes:
        if has_missed_issue:
            return "missed"
        return None

    unique_outcomes = set(predicted_issue_outcomes)
    if len(unique_outcomes) == 1 and not has_missed_issue:
        return predicted_issue_outcomes[0]
    return "mixed"


def _reconcile_issue_outcomes(
    predicted_state: dict | None,
    human_review_outcome: dict | None,
) -> dict[str, Any]:
    predicted_issues = _collect_reconciled_issues(predicted_state)
    actual_issues = _collect_reconciled_issues(human_review_outcome)
    explicit_suggestion_outcomes = _collect_suggestion_outcomes(human_review_outcome)
    actual_approval_state = _extract_approval_state(human_review_outcome)

    issue_outcomes: list[dict[str, Any]] = []
    matched_issue_count = 0

    for issue_key, predicted_issue in sorted(predicted_issues.items()):
        actual_issue = actual_issues.get(issue_key)
        suggestion_outcome = explicit_suggestion_outcomes.get(issue_key)
        if actual_issue is not None:
            matched_issue_count += 1
        resolved_delta = _resolve_issue_delta(
            predicted_issue,
            actual_issue,
            actual_approval_state=actual_approval_state,
            suggestion_outcome=suggestion_outcome,
        )

        actual_summary = (
            actual_issue.get("summary")
            if actual_issue
            else resolved_delta.get("actual_summary")
        )

        issue_outcomes.append(
            {
                "issue_key": issue_key,
                "outcome": resolved_delta["outcome"],
                "outcome_status": resolved_delta["outcome_status"],
                "outcome_source": resolved_delta["outcome_source"],
                "predicted_type": predicted_issue.get("type"),
                "predicted_disposition": predicted_issue.get("disposition"),
                "predicted_summary": predicted_issue.get("summary"),
                "actual_type": actual_issue.get("type") if actual_issue else None,
                "actual_disposition": actual_issue.get("disposition") if actual_issue else None,
                "actual_summary": actual_summary,
                **(
                    {"explicit_outcome": resolved_delta["explicit_outcome"]}
                    if resolved_delta.get("explicit_outcome")
                    else {}
                ),
                **(
                    {"missing_outcome_reason": resolved_delta["missing_outcome_reason"]}
                    if resolved_delta.get("missing_outcome_reason")
                    else {}
                ),
            }
        )

    for issue_key, actual_issue in sorted(actual_issues.items()):
        if issue_key in predicted_issues:
            continue

        issue_outcomes.append(
            {
                "issue_key": issue_key,
                "outcome": "missed",
                "outcome_status": "corrected",
                "outcome_source": "human_review",
                "predicted_type": None,
                "predicted_disposition": None,
                "predicted_summary": None,
                "actual_type": actual_issue.get("type"),
                "actual_disposition": actual_issue.get("disposition"),
                "actual_summary": actual_issue.get("summary"),
            }
        )

    return {
        "terminal_resolution": _terminal_resolution(issue_outcomes),
        "issue_outcomes": issue_outcomes,
        "predicted_issue_count": len(predicted_issues),
        "matched_issue_count": matched_issue_count,
        "actual_issue_count": len(actual_issues),
    }


def _format_issue_outcome_summary(issue_outcomes: Any) -> str | None:
    if not isinstance(issue_outcomes, list):
        return None

    rendered: list[str] = []
    for item in issue_outcomes:
        if not isinstance(item, dict):
            continue
        issue_key = _normalize_issue_key(item.get("issue_key"))
        outcome = _normalize_review_value(item.get("outcome"))
        if issue_key and outcome:
            rendered.append(f"{issue_key}={outcome}")

    return ", ".join(rendered) or None


def _extract_suggestion_outcome_metrics(review_state: dict | None) -> dict[str, Any]:
    outcome_capture = _extract_outcome_capture(review_state)
    if not isinstance(outcome_capture, dict):
        return {}

    metrics: dict[str, Any] = {}

    artifact_outcome = _normalize_review_value(outcome_capture.get("artifact_outcome"))
    if artifact_outcome in _ARTIFACT_OUTCOME_VALUES:
        metrics["artifact_outcome"] = artifact_outcome

    final_disposition = outcome_capture.get("final_disposition")
    if isinstance(final_disposition, str):
        final_disposition = final_disposition.strip()
        if final_disposition:
            metrics["final_disposition"] = final_disposition

    reviewer_summary = outcome_capture.get("reviewer_summary")
    if isinstance(reviewer_summary, str):
        reviewer_summary = reviewer_summary.strip()
        if reviewer_summary:
            metrics["reviewer_summary"] = reviewer_summary

    suggestion_outcomes = outcome_capture.get("suggestion_outcomes")
    if not isinstance(suggestion_outcomes, list):
        return metrics

    compact_suggestion_outcomes: list[dict[str, Any]] = []
    suggestion_outcome_counts: dict[str, int] = {}
    for item in suggestion_outcomes:
        if not isinstance(item, dict):
            continue

        suggestion_key = _normalize_issue_key(
            item.get("suggestion_key") or item.get("issue_key") or item.get("key")
        )
        outcome = _normalize_review_value(item.get("outcome"))
        if not suggestion_key or outcome not in _ARTIFACT_OUTCOME_VALUES:
            continue

        compact_item: dict[str, Any] = {
            "suggestion_key": suggestion_key,
            "outcome": outcome,
        }
        summary = _extract_issue_summary(item)
        if summary:
            compact_item["summary"] = summary

        compact_suggestion_outcomes.append(compact_item)
        suggestion_outcome_counts[outcome] = suggestion_outcome_counts.get(outcome, 0) + 1

    if compact_suggestion_outcomes:
        metrics["suggestion_outcomes"] = compact_suggestion_outcomes
        metrics["suggestion_outcome_counts"] = suggestion_outcome_counts

    return metrics


def _format_suggestion_outcome_summary(suggestion_outcomes: Any) -> str | None:
    if not isinstance(suggestion_outcomes, list):
        return None

    rendered: list[str] = []
    for item in suggestion_outcomes:
        if not isinstance(item, dict):
            continue
        suggestion_key = _normalize_issue_key(item.get("suggestion_key"))
        outcome = _normalize_review_value(item.get("outcome"))
        if suggestion_key and outcome in _ARTIFACT_OUTCOME_VALUES:
            rendered.append(f"{suggestion_key}={outcome}")

    return ", ".join(rendered) or None


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


def _safe_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _prediction_feedback_provenance(cycle: ReviewCycle) -> dict[str, Any]:
    return {
        "review_cycle_id": cycle.id,
        "cycle_type": "review_cycle",
        "source_type": cycle.source_type,
        "source_external_id": cycle.external_id,
        "target": _review_cycle_target(cycle),
        "metadata_json": cycle.metadata_json if isinstance(cycle.metadata_json, dict) else {},
        "predicted_at": _safe_iso(cycle.predicted_at),
        "human_reviewed_at": _safe_iso(cycle.human_reviewed_at),
    }


def _build_approval_feedback_memory(cycle: ReviewCycle) -> PredictionFeedbackMemory | None:
    predicted_approval_state = _extract_approval_state(cycle.predicted_state)
    actual_approval_state = _extract_approval_state(cycle.human_review_outcome)
    if predicted_approval_state is None and actual_approval_state is None:
        return None

    if predicted_approval_state is None or actual_approval_state is None:
        outcome_status = "unknown"
        delta_type = "unknown"
        reason = "Predicted or actual approval state is missing; approval delta is ambiguous."
    elif predicted_approval_state == actual_approval_state:
        outcome_status = "accepted"
        delta_type = "confirmed"
        reason = "Predicted approval state matched the human review outcome."
    else:
        outcome_status = "corrected"
        delta_type = "approval_changed"
        reason = "Human review outcome corrected the predicted approval state."

    delta = {
        "predicted_approval_state": predicted_approval_state,
        "actual_approval_state": actual_approval_state,
        "outcome_status": outcome_status,
        "delta_type": delta_type,
        "reason": reason,
    }

    return PredictionFeedbackMemory(
        mini_id=cycle.mini_id,
        cycle_type="review_cycle",
        cycle_id=cycle.id,
        source_type=cycle.source_type,
        external_id=cycle.external_id,
        feedback_kind="approval_delta",
        outcome_status=outcome_status,
        delta_type=delta_type,
        issue_key=None,
        predicted_private_assessment=cycle.predicted_state.get("private_assessment")
        if isinstance(cycle.predicted_state, dict)
        else None,
        predicted_expressed_feedback=cycle.predicted_state.get("expressed_feedback")
        if isinstance(cycle.predicted_state, dict)
        else None,
        actual_reviewer_behavior={
            "approval_state": actual_approval_state,
            "expressed_feedback": cycle.human_review_outcome.get("expressed_feedback")
            if isinstance(cycle.human_review_outcome, dict)
            else None,
        },
        raw_outcome=cycle.human_review_outcome
        if isinstance(cycle.human_review_outcome, dict)
        else None,
        delta=delta,
        provenance=_prediction_feedback_provenance(cycle),
    )


def _build_issue_feedback_memory(
    cycle: ReviewCycle,
    issue_delta: dict[str, Any],
) -> PredictionFeedbackMemory | None:
    issue_key = _normalize_issue_key(issue_delta.get("issue_key"))
    delta_type = _normalize_review_value(issue_delta.get("outcome")) or "unknown"
    outcome_status = _normalize_review_value(issue_delta.get("outcome_status")) or "unknown"
    if issue_key is None and delta_type == "unknown":
        return None

    predicted_private = {
        "issue_key": issue_key,
        "type": issue_delta.get("predicted_type"),
        "disposition": issue_delta.get("predicted_disposition"),
        "summary": issue_delta.get("predicted_summary"),
    }
    predicted_expressed = {
        "approval_state": _extract_approval_state(cycle.predicted_state),
        "issue_key": issue_key,
        "type": issue_delta.get("predicted_type"),
        "disposition": issue_delta.get("predicted_disposition"),
        "summary": issue_delta.get("predicted_summary"),
    }
    actual_behavior = {
        "approval_state": _extract_approval_state(cycle.human_review_outcome),
        "issue_key": issue_key,
        "type": issue_delta.get("actual_type"),
        "disposition": issue_delta.get("actual_disposition"),
        "summary": issue_delta.get("actual_summary"),
        "outcome_source": issue_delta.get("outcome_source"),
        "explicit_outcome": issue_delta.get("explicit_outcome"),
    }

    return PredictionFeedbackMemory(
        mini_id=cycle.mini_id,
        cycle_type="review_cycle",
        cycle_id=cycle.id,
        source_type=cycle.source_type,
        external_id=cycle.external_id,
        feedback_kind="issue_delta",
        outcome_status=outcome_status,
        delta_type=delta_type,
        issue_key=issue_key,
        predicted_private_assessment=predicted_private,
        predicted_expressed_feedback=predicted_expressed,
        actual_reviewer_behavior=actual_behavior,
        raw_outcome=cycle.human_review_outcome
        if isinstance(cycle.human_review_outcome, dict)
        else None,
        delta=dict(issue_delta),
        provenance=_prediction_feedback_provenance(cycle),
    )


def _build_prediction_feedback_memories(cycle: ReviewCycle) -> list[PredictionFeedbackMemory]:
    memories: list[PredictionFeedbackMemory] = []

    approval_memory = _build_approval_feedback_memory(cycle)
    if approval_memory is not None:
        memories.append(approval_memory)

    if isinstance(cycle.delta_metrics, dict):
        issue_outcomes = cycle.delta_metrics.get("issue_outcomes")
        if isinstance(issue_outcomes, list):
            for issue_delta in issue_outcomes:
                if not isinstance(issue_delta, dict):
                    continue
                memory = _build_issue_feedback_memory(cycle, issue_delta)
                if memory is not None:
                    memories.append(memory)

    return memories


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
    feedback_summary = _extract_reviewer_summary(cycle.human_review_outcome)
    finding_content = (
        f"{marker} Review outcome calibration for {target}: "
        f"predicted approval_state={predicted_approval_state}, "
        f"actual approval_state={actual_approval_state}, "
        f"approval_state_changed={'yes' if approval_state_changed else 'no'}."
    )
    if isinstance(cycle.delta_metrics, dict):
        terminal_resolution = _normalize_review_value(cycle.delta_metrics.get("terminal_resolution"))
        if terminal_resolution:
            finding_content += f" terminal_resolution={terminal_resolution}."

        artifact_outcome = _normalize_review_value(cycle.delta_metrics.get("artifact_outcome"))
        if artifact_outcome in _ARTIFACT_OUTCOME_VALUES:
            finding_content += f" artifact_outcome={artifact_outcome}."

        final_disposition = cycle.delta_metrics.get("final_disposition")
        if isinstance(final_disposition, str):
            final_disposition = final_disposition.strip()
            if final_disposition:
                finding_content += f" final_disposition={final_disposition}."

        issue_outcome_summary = _format_issue_outcome_summary(
            cycle.delta_metrics.get("issue_outcomes")
        )
        if issue_outcome_summary:
            finding_content += f" issue_outcomes={issue_outcome_summary}."

        suggestion_outcome_summary = _format_suggestion_outcome_summary(
            cycle.delta_metrics.get("suggestion_outcomes")
        )
        if suggestion_outcome_summary:
            finding_content += f" suggestion_outcomes={suggestion_outcome_summary}."

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

    for memory in _build_prediction_feedback_memories(cycle):
        session.add(memory)

    await _apply_framework_confidence_deltas(session, cycle)


async def _apply_framework_confidence_deltas(
    session: AsyncSession,
    cycle: ReviewCycle,
) -> None:
    """Feed issue_outcomes from a finalized cycle into framework confidence scores."""
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

    # Fetch only principles_json — avoids loading the full ORM object which may
    # have columns absent in test schemas.
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
            "framework_confidence_delta mini_id=%s cycle_id=%s updates=%d",
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
                        "source": "review_writeback",
                    },
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


async def list_prediction_feedback_memories(
    session: AsyncSession,
    mini_id: str,
    *,
    limit: int = 100,
    cycle_id: str | None = None,
    outcome_status: str | None = None,
) -> list[PredictionFeedbackMemory]:
    """Return recent first-class prediction feedback memories for one mini."""
    stmt = select(PredictionFeedbackMemory).where(
        PredictionFeedbackMemory.mini_id == mini_id,
    )
    if cycle_id:
        stmt = stmt.where(PredictionFeedbackMemory.cycle_id == cycle_id)
    if outcome_status:
        stmt = stmt.where(PredictionFeedbackMemory.outcome_status == outcome_status)

    stmt = stmt.order_by(PredictionFeedbackMemory.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def build_calibration_note(
    session: AsyncSession,
    mini_id: str,
    *,
    limit: int = 5,
) -> str | None:
    """Build a short calibration note from the most recent closed review cycles.

    Pulls the last *limit* cycles that have a human_review_outcome, computes
    avg blocker precision/recall via the shared calculate_metrics helper, and
    returns a Markdown note suitable for injection into the predictor system
    prompt.  Returns None when there is insufficient data (<2 closed cycles).
    """
    from scripts.calculate_review_agreement import calculate_metrics  # local import — script path

    stmt = (
        select(ReviewCycle)
        .where(
            ReviewCycle.mini_id == mini_id,
            ReviewCycle.human_review_outcome.is_not(None),
        )
        .order_by(ReviewCycle.human_reviewed_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    cycles = list(result.scalars().all())

    if len(cycles) < 2:
        return None

    metrics = calculate_metrics(cycles)
    if metrics is None:
        return None

    blocker_prec: float = metrics.get("blocker_precision", 0.0) or 0.0
    blocker_rec: float = metrics.get("blocker_recall", 0.0) or 0.0
    approval_acc: float = metrics.get("approval_accuracy", 0.0) or 0.0
    count: int = metrics.get("count", len(cycles))

    # Derive a plain-language calibration hint
    hints: list[str] = []
    if blocker_prec < 0.60:
        hints.append(
            "You tend to flag too many issues that the reviewer doesn't block on — "
            "tighten your blocker criteria."
        )
    elif blocker_prec > 0.85:
        hints.append("Your blocker predictions are high precision — maintain current selectivity.")
    if blocker_rec < 0.60:
        hints.append(
            "You tend to miss blockers the reviewer raised — be more thorough in "
            "flagging risky patterns."
        )
    if approval_acc < 0.60:
        hints.append(
            "Your approval state predictions have been off — recalibrate whether to "
            "approve vs. request changes."
        )

    lines = [
        f"## Recent Calibration (last {count} review{'s' if count != 1 else ''})",
        f"Avg blocker precision: {blocker_prec:.2f}, recall: {blocker_rec:.2f}, "
        f"approval accuracy: {approval_acc:.2f}.",
    ]
    if hints:
        lines.append(" ".join(hints))

    return "\n".join(lines)


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
    delta_metrics.update(_extract_suggestion_outcome_metrics(human_review_outcome))

    reconciliation = _reconcile_issue_outcomes(cycle.predicted_state, human_review_outcome)
    if reconciliation["terminal_resolution"] is not None:
        delta_metrics["terminal_resolution"] = reconciliation["terminal_resolution"]
    delta_metrics["issue_outcomes"] = reconciliation["issue_outcomes"]
    delta_metrics["predicted_issue_count"] = reconciliation["predicted_issue_count"]
    delta_metrics["matched_issue_count"] = reconciliation["matched_issue_count"]
    delta_metrics["actual_issue_count"] = reconciliation["actual_issue_count"]

    cycle.human_review_outcome = human_review_outcome
    cycle.delta_metrics = delta_metrics
    cycle.human_reviewed_at = datetime.now(UTC)
    await _writeback_review_cycle_learning(session, cycle)

    await session.commit()
    await session.refresh(cycle)
    return cycle
