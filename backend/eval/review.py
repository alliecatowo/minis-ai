"""Structured held-out review expectations and agreement scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

ReviewVerdict = Literal["approve", "request_changes", "comment", "unclear"]
ReviewAgreementStatus = Literal["scored", "insufficient_data"]


def normalize_review_verdict(value: str | None) -> ReviewVerdict:
    """Normalize loose verdict strings to a small canonical set."""
    if not value:
        return "unclear"

    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "approve": "approve",
        "approved": "approve",
        "lgtm": "approve",
        "comment": "comment",
        "comment_only": "comment",
        "comments": "comment",
        "request_changes": "request_changes",
        "changes_requested": "request_changes",
        "request_change": "request_changes",
        "requesting_changes": "request_changes",
        "block": "request_changes",
        "blocked": "request_changes",
        "reject": "request_changes",
        "rejected": "request_changes",
        "unclear": "unclear",
        "unknown": "unclear",
    }
    return mapping.get(normalized, "unclear")


@dataclass
class ReviewCandidate:
    """Candidate issue that a held-out review may or may not select."""

    id: str
    summary: str
    expected: bool = False
    private_expected: bool | None = None
    should_surface: bool | None = None
    expected_rank: int | None = None
    expected_confidence: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ReviewCandidate":
        expected_rank = data.get("expected_rank")
        expected_confidence = data.get("expected_confidence")
        return cls(
            id=str(data["id"]),
            summary=str(data["summary"]),
            expected=bool(data.get("expected", False)),
            private_expected=(
                bool(data["private_expected"]) if "private_expected" in data else None
            ),
            should_surface=(
                bool(data["should_surface"]) if "should_surface" in data else None
            ),
            expected_rank=int(expected_rank) if expected_rank is not None else None,
            expected_confidence=(
                float(expected_confidence) if expected_confidence is not None else None
            ),
        )


@dataclass
class HeldOutReviewExpectation:
    """Structured held-out review labels for a review-prediction turn."""

    verdict: ReviewVerdict
    blocker_candidates: list[ReviewCandidate] = field(default_factory=list)
    comment_candidates: list[ReviewCandidate] = field(default_factory=list)
    audience_transfer: bool = False
    source_audience: str | None = None
    target_audience: str | None = None
    expected_confidence: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "HeldOutReviewExpectation":
        expected_confidence = data.get("expected_confidence")
        return cls(
            verdict=normalize_review_verdict(str(data.get("verdict", ""))),
            blocker_candidates=[
                ReviewCandidate.from_dict(item) for item in list(data.get("blocker_candidates", []))
            ],
            comment_candidates=[
                ReviewCandidate.from_dict(item) for item in list(data.get("comment_candidates", []))
            ],
            audience_transfer=bool(data.get("audience_transfer", False)),
            source_audience=(
                str(data["source_audience"]) if data.get("source_audience") else None
            ),
            target_audience=(
                str(data["target_audience"]) if data.get("target_audience") else None
            ),
            expected_confidence=(
                float(expected_confidence) if expected_confidence is not None else None
            ),
        )

    @property
    def expected_blocker_ids(self) -> list[str]:
        return [candidate.id for candidate in self.blocker_candidates if candidate.expected]

    @property
    def expected_comment_ids(self) -> list[str]:
        return [candidate.id for candidate in self.comment_candidates if candidate.expected]

    @property
    def all_candidates(self) -> list[ReviewCandidate]:
        return [*self.blocker_candidates, *self.comment_candidates]

    @property
    def private_expected_ids(self) -> list[str]:
        return [
            candidate.id
            for candidate in self.all_candidates
            if candidate.private_expected is True
        ]

    @property
    def private_labels_available(self) -> bool:
        return any(candidate.private_expected is not None for candidate in self.all_candidates)

    @property
    def expected_expressed_ids(self) -> list[str]:
        candidates = [
            candidate
            for candidate in self.all_candidates
            if candidate.expected
        ]
        if any(candidate.expected_rank is not None for candidate in candidates):
            candidates = sorted(
                candidates,
                key=lambda candidate: (
                    candidate.expected_rank is None,
                    candidate.expected_rank or 0,
                ),
            )
        return [candidate.id for candidate in candidates]

    @property
    def confidence_labels_available(self) -> bool:
        return self.expected_confidence is not None or any(
            candidate.expected_confidence is not None for candidate in self.all_candidates
        )


class ReviewSelection(BaseModel):
    """Judge-extracted review selection from the mini's response."""

    predicted_verdict: ReviewVerdict | None = Field(
        default=None,
        description="Predicted review verdict extracted from the mini response.",
    )
    selected_private_assessment_ids: list[str] | None = Field(
        default=None,
        description="IDs of candidates the mini identifies as latent/private critique.",
    )
    selected_expressed_feedback_ids: list[str] | None = Field(
        default=None,
        description="IDs of candidates the mini chooses to surface to the author/context.",
    )
    selected_blocker_ids: list[str] = Field(
        default_factory=list,
        description="Legacy IDs of blocker candidates effectively raised by the mini.",
    )
    selected_comment_ids: list[str] = Field(
        default_factory=list,
        description="Legacy IDs of non-blocking comment candidates effectively raised by the mini.",
    )
    rationale: str = Field(
        default="No review selection provided.",
        description="Brief explanation of the extracted review selection.",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional confidence the response assigns to its review prediction.",
    )


class ReviewAgreement(BaseModel):
    """Deterministic agreement metrics for a held-out review turn."""

    status: ReviewAgreementStatus = "scored"
    insufficient_data_reason: str | None = None
    expected_verdict: ReviewVerdict
    predicted_verdict: ReviewVerdict
    verdict_match: bool
    blocker_precision: float = Field(ge=0.0, le=1.0)
    blocker_recall: float = Field(ge=0.0, le=1.0)
    blocker_f1: float = Field(ge=0.0, le=1.0)
    comment_precision: float = Field(ge=0.0, le=1.0)
    comment_recall: float = Field(ge=0.0, le=1.0)
    comment_f1: float = Field(ge=0.0, le=1.0)
    private_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    private_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    private_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    expressed_order_score: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_error: float | None = Field(default=None, ge=0.0, le=1.0)
    audience_transfer: bool = False
    unavailable_metrics: list[str] = Field(default_factory=list)
    overall_agreement: float = Field(ge=0.0, le=1.0)


def _precision_recall_f1(
    expected_ids: set[str],
    predicted_ids: set[str],
) -> tuple[float, float, float]:
    """Compute strict agreement metrics with sane empty-set behavior."""
    if not expected_ids and not predicted_ids:
        return 1.0, 1.0, 1.0
    if not expected_ids or not predicted_ids:
        return 0.0, 0.0, 0.0

    true_positives = len(expected_ids & predicted_ids)
    precision = true_positives / len(predicted_ids)
    recall = true_positives / len(expected_ids)
    if precision + recall == 0:
        return precision, recall, 0.0
    return precision, recall, 2 * precision * recall / (precision + recall)


def _pairwise_order_score(
    expected_order: list[str],
    predicted_order: list[str],
) -> float | None:
    """Score relative ordering for selected expected issue IDs.

    Returns None when fewer than two expected IDs overlap the prediction because
    order cannot be measured from a single common item.
    """
    expected_positions = {item_id: index for index, item_id in enumerate(expected_order)}
    predicted_filtered = [item_id for item_id in predicted_order if item_id in expected_positions]
    if len(predicted_filtered) < 2:
        return None

    correct = 0
    total = 0
    for left_index, left_id in enumerate(predicted_filtered):
        for right_id in predicted_filtered[left_index + 1:]:
            total += 1
            if expected_positions[left_id] < expected_positions[right_id]:
                correct += 1
    if total == 0:
        return None
    return correct / total


def _confidence_error(expectation: HeldOutReviewExpectation, selection: ReviewSelection) -> float | None:
    """Compute absolute confidence error when both sides expose confidence labels."""
    if selection.confidence is None:
        return None
    if expectation.expected_confidence is not None:
        return abs(expectation.expected_confidence - selection.confidence)

    expected_candidates = [
        candidate
        for candidate in expectation.all_candidates
        if candidate.expected and candidate.expected_confidence is not None
    ]
    if not expected_candidates:
        return None
    expected = sum(candidate.expected_confidence or 0.0 for candidate in expected_candidates) / len(
        expected_candidates
    )
    return abs(expected - selection.confidence)


def _insufficient_review_agreement(
    expectation: HeldOutReviewExpectation,
    reason: str,
    predicted_verdict: ReviewVerdict = "unclear",
) -> ReviewAgreement:
    expected_verdict = normalize_review_verdict(expectation.verdict)
    return ReviewAgreement(
        status="insufficient_data",
        insufficient_data_reason=reason,
        expected_verdict=expected_verdict,
        predicted_verdict=predicted_verdict,
        verdict_match=False,
        blocker_precision=0.0,
        blocker_recall=0.0,
        blocker_f1=0.0,
        comment_precision=0.0,
        comment_recall=0.0,
        comment_f1=0.0,
        private_precision=0.0 if expectation.private_labels_available else None,
        private_recall=0.0 if expectation.private_labels_available else None,
        private_f1=0.0 if expectation.private_labels_available else None,
        expressed_order_score=None,
        confidence_error=None,
        audience_transfer=expectation.audience_transfer,
        unavailable_metrics=["insufficient_data"],
        overall_agreement=0.0,
    )


def _legacy_selected_ids(selection: ReviewSelection) -> list[str]:
    return [*selection.selected_blocker_ids, *selection.selected_comment_ids]


def _selected_blocker_ids(expectation: HeldOutReviewExpectation, selection: ReviewSelection) -> list[str]:
    if selection.selected_blocker_ids:
        return selection.selected_blocker_ids
    if selection.selected_expressed_feedback_ids is None:
        return selection.selected_blocker_ids

    blocker_ids = {candidate.id for candidate in expectation.blocker_candidates}
    return [
        candidate_id
        for candidate_id in selection.selected_expressed_feedback_ids
        if candidate_id in blocker_ids
    ]


def _selected_comment_ids(expectation: HeldOutReviewExpectation, selection: ReviewSelection) -> list[str]:
    if selection.selected_comment_ids:
        return selection.selected_comment_ids
    if selection.selected_expressed_feedback_ids is None:
        return selection.selected_comment_ids

    comment_ids = {candidate.id for candidate in expectation.comment_candidates}
    return [
        candidate_id
        for candidate_id in selection.selected_expressed_feedback_ids
        if candidate_id in comment_ids
    ]


def compute_review_agreement(
    expectation: HeldOutReviewExpectation,
    selection: ReviewSelection | None,
) -> ReviewAgreement:
    """Score review agreement from fixed candidate IDs."""
    if selection is None:
        return _insufficient_review_agreement(expectation, "review_selection missing")

    predicted_verdict = normalize_review_verdict(selection.predicted_verdict)
    expected_verdict = normalize_review_verdict(expectation.verdict)
    if expected_verdict != "unclear" and predicted_verdict == "unclear":
        return _insufficient_review_agreement(
            expectation,
            "predicted_verdict missing_or_unclear",
            predicted_verdict=predicted_verdict,
        )

    verdict_match = predicted_verdict == expected_verdict
    selected_blocker_ids = _selected_blocker_ids(expectation, selection)
    selected_comment_ids = _selected_comment_ids(expectation, selection)

    blocker_precision, blocker_recall, blocker_f1 = _precision_recall_f1(
        set(expectation.expected_blocker_ids),
        set(selected_blocker_ids),
    )
    comment_precision, comment_recall, comment_f1 = _precision_recall_f1(
        set(expectation.expected_comment_ids),
        set(selected_comment_ids),
    )
    private_precision = private_recall = private_f1 = None
    if expectation.private_labels_available:
        private_predicted_ids = (
            selection.selected_private_assessment_ids
            if selection.selected_private_assessment_ids is not None
            else _legacy_selected_ids(selection)
        )
        private_precision, private_recall, private_f1 = _precision_recall_f1(
            set(expectation.private_expected_ids),
            set(private_predicted_ids),
        )

    predicted_expressed_ids = (
        selection.selected_expressed_feedback_ids
        if selection.selected_expressed_feedback_ids is not None
        else [*selected_blocker_ids, *selected_comment_ids]
    )
    expressed_order_score = _pairwise_order_score(
        expectation.expected_expressed_ids,
        predicted_expressed_ids,
    )
    confidence_error = _confidence_error(expectation, selection)

    unavailable_metrics: list[str] = []
    if not expectation.private_labels_available:
        unavailable_metrics.append("private_vs_expressed")
    if expressed_order_score is None:
        unavailable_metrics.append("comment_order")
    if confidence_error is None:
        unavailable_metrics.append("calibration_confidence")

    overall_components = [1.0 if verdict_match else 0.0]
    if expectation.blocker_candidates:
        overall_components.append(blocker_f1)
    if expectation.comment_candidates:
        overall_components.append(comment_f1)

    return ReviewAgreement(
        expected_verdict=expected_verdict,
        predicted_verdict=predicted_verdict,
        verdict_match=verdict_match,
        blocker_precision=blocker_precision,
        blocker_recall=blocker_recall,
        blocker_f1=blocker_f1,
        comment_precision=comment_precision,
        comment_recall=comment_recall,
        comment_f1=comment_f1,
        private_precision=private_precision,
        private_recall=private_recall,
        private_f1=private_f1,
        expressed_order_score=expressed_order_score,
        confidence_error=confidence_error,
        audience_transfer=expectation.audience_transfer,
        unavailable_metrics=unavailable_metrics,
        overall_agreement=sum(overall_components) / len(overall_components),
    )
