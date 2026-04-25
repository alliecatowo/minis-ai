"""Gold review-prediction case fixtures and validation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from eval.review import HeldOutReviewExpectation, ReviewCandidate, normalize_review_verdict

ReviewCaseType = Literal[
    "architecture_domain_boundary",
    "pragmatic_shipping_tradeoff",
    "audience_context_sensitive_suppression",
    "recency_vs_durable_framework",
    "novel_work_generalization",
]


class GoldEvidenceReference(BaseModel):
    """Provenance for why a gold label exists."""

    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    item_type: str = Field(min_length=1)
    external_id: str | None = None
    url: str | None = None
    quote: str | None = None
    note: str = Field(min_length=1)


class GoldReviewCaseInput(BaseModel):
    """Review-prediction request payload covered by a gold case."""

    artifact_type: Literal["pull_request"] = "pull_request"
    repo_name: str | None = None
    title: str | None = None
    description: str | None = None
    diff_summary: str | None = None
    artifact_summary: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    author_model: Literal["junior_peer", "trusted_peer", "senior_peer", "unknown"] = "unknown"
    delivery_context: Literal["hotfix", "normal", "exploratory", "incident"] = "normal"

    @model_validator(mode="after")
    def validate_review_input_present(self) -> "GoldReviewCaseInput":
        if any(
            [
                self.title and self.title.strip(),
                self.description and self.description.strip(),
                self.diff_summary and self.diff_summary.strip(),
                self.artifact_summary and self.artifact_summary.strip(),
                self.changed_files,
            ]
        ):
            return self
        raise ValueError("Gold review cases must include at least one review input field")


class GoldTargetAudience(BaseModel):
    """The audience and delivery context the reviewer is calibrating for."""

    author_model: Literal["junior_peer", "trusted_peer", "senior_peer", "unknown"]
    delivery_context: Literal["hotfix", "normal", "exploratory", "incident"]
    reviewer_surface: Literal["github_app", "cli_pre_review", "mcp", "chat"] = "github_app"
    notes: str = Field(min_length=1)


class GoldAssessmentSignal(BaseModel):
    """Expected private-assessment signal."""

    key: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[str] = Field(default_factory=list)
    should_surface: bool = True


class GoldPrivateAssessment(BaseModel):
    """Expected private assessment before audience/context filtering."""

    blocking_issues: list[GoldAssessmentSignal] = Field(default_factory=list)
    non_blocking_issues: list[GoldAssessmentSignal] = Field(default_factory=list)
    open_questions: list[GoldAssessmentSignal] = Field(default_factory=list)
    positive_signals: list[GoldAssessmentSignal] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_at_least_one_signal(self) -> "GoldPrivateAssessment":
        if (
            self.blocking_issues
            or self.non_blocking_issues
            or self.open_questions
            or self.positive_signals
        ):
            return self
        raise ValueError("Gold review cases must include at least one private signal")


class GoldExpressedComment(BaseModel):
    """Expected expressed review comment after filtering private assessment."""

    type: Literal["blocker", "note", "question", "praise"]
    disposition: Literal["request_changes", "comment", "approve"]
    issue_key: str | None = None
    summary: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class GoldExpressedFeedback(BaseModel):
    """Expected feedback the reviewer would actually say."""

    summary: str = Field(min_length=1)
    comments: list[GoldExpressedComment] = Field(default_factory=list)
    approval_state: Literal["approve", "comment", "request_changes", "uncertain"]
    suppressed_private_signal_keys: list[str] = Field(default_factory=list)


class GoldScoringDimension(BaseModel):
    """Dimension used to judge a review prediction against a gold case."""

    name: str = Field(min_length=1)
    weight: float = Field(gt=0.0, le=1.0)
    rubric: str = Field(min_length=1)
    expected_signal_keys: list[str] = Field(default_factory=list)
    required: bool = True


class GoldReviewCase(BaseModel):
    """A single held-out review prediction calibration case."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    case_type: ReviewCaseType
    intent: str = Field(min_length=1)
    target_audience: GoldTargetAudience
    input: GoldReviewCaseInput
    expected_private_assessment: GoldPrivateAssessment
    expected_expressed_feedback: GoldExpressedFeedback
    evidence_references: list[GoldEvidenceReference] = Field(min_length=1)
    scoring_dimensions: list[GoldScoringDimension] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cross_references(self) -> "GoldReviewCase":
        if self.target_audience.author_model != self.input.author_model:
            raise ValueError(
                f"Target audience author_model must match input author_model in {self.id}"
            )
        if self.target_audience.delivery_context != self.input.delivery_context:
            raise ValueError(
                f"Target audience delivery_context must match input delivery_context in {self.id}"
            )

        evidence_ids = {ref.id for ref in self.evidence_references}
        if len(evidence_ids) != len(self.evidence_references):
            raise ValueError(f"Duplicate evidence reference id in {self.id}")

        signal_keys = set()
        for signal in self.private_signals:
            signal_keys.add(signal.key)
            missing = set(signal.evidence_refs) - evidence_ids
            if missing:
                raise ValueError(
                    f"Unknown evidence refs in {self.id}/{signal.key}: {sorted(missing)}"
                )

        expressed_issue_keys = {
            comment.issue_key for comment in self.expected_expressed_feedback.comments if comment.issue_key
        }
        unknown_issue_keys = expressed_issue_keys - signal_keys
        if unknown_issue_keys:
            raise ValueError(
                f"Expressed comments reference unknown private signals in {self.id}: "
                f"{sorted(unknown_issue_keys)}"
            )

        suppressed_keys = set(self.expected_expressed_feedback.suppressed_private_signal_keys)
        unknown_suppressed = suppressed_keys - signal_keys
        if unknown_suppressed:
            raise ValueError(
                f"Suppressed keys are not private signals in {self.id}: {sorted(unknown_suppressed)}"
            )

        for dimension in self.scoring_dimensions:
            unknown_dimension_keys = set(dimension.expected_signal_keys) - signal_keys
            if unknown_dimension_keys:
                raise ValueError(
                    f"Scoring dimension {dimension.name} references unknown signals in "
                    f"{self.id}: {sorted(unknown_dimension_keys)}"
                )

        total_weight = sum(dimension.weight for dimension in self.scoring_dimensions)
        if abs(total_weight - 1.0) > 0.001:
            raise ValueError(f"Scoring dimension weights must sum to 1.0 in {self.id}")

        return self

    @property
    def private_signals(self) -> list[GoldAssessmentSignal]:
        return [
            *self.expected_private_assessment.blocking_issues,
            *self.expected_private_assessment.non_blocking_issues,
            *self.expected_private_assessment.open_questions,
            *self.expected_private_assessment.positive_signals,
        ]

    def to_held_out_review_expectation(self) -> HeldOutReviewExpectation:
        """Convert a gold case into the existing held-out agreement shape."""
        expressed_issue_keys = {
            comment.issue_key
            for comment in self.expected_expressed_feedback.comments
            if comment.issue_key
        }
        blocker_candidates = [
            ReviewCandidate(
                id=signal.key,
                summary=signal.summary,
                expected=signal.should_surface and signal.key in expressed_issue_keys,
            )
            for signal in self.expected_private_assessment.blocking_issues
        ]
        comment_candidates = [
            ReviewCandidate(
                id=signal.key,
                summary=signal.summary,
                expected=signal.should_surface and signal.key in expressed_issue_keys,
            )
            for signal in [
                *self.expected_private_assessment.non_blocking_issues,
                *self.expected_private_assessment.open_questions,
                *self.expected_private_assessment.positive_signals,
            ]
        ]
        return HeldOutReviewExpectation(
            verdict=normalize_review_verdict(self.expected_expressed_feedback.approval_state),
            blocker_candidates=blocker_candidates,
            comment_candidates=comment_candidates,
        )

    def to_golden_turn_dict(self) -> dict[str, object]:
        """Adapt a gold review case for the existing chat fidelity runner."""
        expectation = self.to_held_out_review_expectation()
        request = self.input
        prompt = (
            "Predict the review for this pull request.\n\n"
            f"Audience: {self.target_audience.author_model}; "
            f"context: {self.target_audience.delivery_context}; "
            f"surface: {self.target_audience.reviewer_surface}.\n"
            f"Repo: {request.repo_name or 'unknown'}\n"
            f"Title: {request.title or '(untitled)'}\n\n"
            f"Description:\n{request.description or '(none)'}\n\n"
            f"Diff summary:\n{request.diff_summary or request.artifact_summary or '(none)'}\n\n"
            f"Changed files: {', '.join(request.changed_files) or '(not provided)'}"
        )
        reference_answer = (
            f"# GOLD REVIEW CASE: {self.id}\n"
            f"# Intent: {self.intent.strip()}\n\n"
            "## expected_private_assessment\n"
            f"{self.expected_private_assessment.model_dump()}\n\n"
            "## expected_expressed_feedback\n"
            f"{self.expected_expressed_feedback.model_dump()}\n\n"
            "## Evidence References\n"
            f"{[ref.model_dump() for ref in self.evidence_references]}"
        )
        return {
            "id": self.id,
            "case_type": "gold_review_case",
            "prompt": prompt,
            "reference_answer": reference_answer,
            "rubric": [
                {dimension.name: dimension.rubric}
                for dimension in self.scoring_dimensions
            ],
            "held_out_review": {
                "verdict": expectation.verdict,
                "blocker_candidates": [
                    {
                        "id": candidate.id,
                        "summary": candidate.summary,
                        "expected": candidate.expected,
                    }
                    for candidate in expectation.blocker_candidates
                ],
                "comment_candidates": [
                    {
                        "id": candidate.id,
                        "summary": candidate.summary,
                        "expected": candidate.expected,
                    }
                    for candidate in expectation.comment_candidates
                ],
            },
        }


class GoldReviewCaseFile(BaseModel):
    """Versioned YAML file containing gold review cases for one subject."""

    version: Literal[1]
    subject: str = Field(min_length=1)
    cases: list[GoldReviewCase] = Field(min_length=1)

    @classmethod
    def from_yaml(cls, path: Path) -> "GoldReviewCaseFile":
        data = yaml.safe_load(path.read_text())
        return cls.model_validate(data)


def load_gold_review_case_files(paths: list[Path]) -> list[GoldReviewCaseFile]:
    """Load and validate multiple gold review-case YAML files."""
    return [GoldReviewCaseFile.from_yaml(path) for path in paths]
