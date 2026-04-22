"""Structured held-out review expectations and agreement scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

ReviewVerdict = Literal["approve", "request_changes", "comment", "unclear"]


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

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ReviewCandidate":
        return cls(
            id=str(data["id"]),
            summary=str(data["summary"]),
            expected=bool(data.get("expected", False)),
        )


@dataclass
class HeldOutReviewExpectation:
    """Structured held-out review labels for a review-prediction turn."""

    verdict: ReviewVerdict
    blocker_candidates: list[ReviewCandidate] = field(default_factory=list)
    comment_candidates: list[ReviewCandidate] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "HeldOutReviewExpectation":
        return cls(
            verdict=normalize_review_verdict(str(data.get("verdict", ""))),
            blocker_candidates=[
                ReviewCandidate.from_dict(item) for item in list(data.get("blocker_candidates", []))
            ],
            comment_candidates=[
                ReviewCandidate.from_dict(item) for item in list(data.get("comment_candidates", []))
            ],
        )

    @property
    def expected_blocker_ids(self) -> list[str]:
        return [candidate.id for candidate in self.blocker_candidates if candidate.expected]

    @property
    def expected_comment_ids(self) -> list[str]:
        return [candidate.id for candidate in self.comment_candidates if candidate.expected]


class ReviewSelection(BaseModel):
    """Judge-extracted review selection from the mini's response."""

    predicted_verdict: ReviewVerdict = Field(
        default="unclear",
        description="Predicted review verdict extracted from the mini response.",
    )
    selected_blocker_ids: list[str] = Field(
        default_factory=list,
        description="IDs of blocker candidates effectively raised by the mini.",
    )
    selected_comment_ids: list[str] = Field(
        default_factory=list,
        description="IDs of non-blocker comment candidates effectively raised by the mini.",
    )
    rationale: str = Field(
        default="No review selection provided.",
        description="Brief explanation of the extracted review selection.",
    )


class ReviewAgreement(BaseModel):
    """Deterministic agreement metrics for a held-out review turn."""

    expected_verdict: ReviewVerdict
    predicted_verdict: ReviewVerdict
    verdict_match: bool
    blocker_precision: float = Field(ge=0.0, le=1.0)
    blocker_recall: float = Field(ge=0.0, le=1.0)
    blocker_f1: float = Field(ge=0.0, le=1.0)
    comment_precision: float = Field(ge=0.0, le=1.0)
    comment_recall: float = Field(ge=0.0, le=1.0)
    comment_f1: float = Field(ge=0.0, le=1.0)
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


def compute_review_agreement(
    expectation: HeldOutReviewExpectation,
    selection: ReviewSelection | None,
) -> ReviewAgreement:
    """Score review agreement from fixed candidate IDs."""
    resolved_selection = selection or ReviewSelection()

    predicted_verdict = normalize_review_verdict(resolved_selection.predicted_verdict)
    expected_verdict = normalize_review_verdict(expectation.verdict)
    verdict_match = predicted_verdict == expected_verdict

    blocker_precision, blocker_recall, blocker_f1 = _precision_recall_f1(
        set(expectation.expected_blocker_ids),
        set(resolved_selection.selected_blocker_ids),
    )
    comment_precision, comment_recall, comment_f1 = _precision_recall_f1(
        set(expectation.expected_comment_ids),
        set(resolved_selection.selected_comment_ids),
    )

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
        overall_agreement=sum(overall_components) / len(overall_components),
    )
