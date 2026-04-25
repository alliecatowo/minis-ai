"""Deterministic review-prediction baselines for held-out review cases."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from eval.review import (
    HeldOutReviewExpectation,
    ReviewAgreement,
    ReviewCandidate,
    ReviewSelection,
    compute_review_agreement,
)

BaselineName = Literal["generic_reviewer", "retrieval_only_similarity"]

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+-]*")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}
_GENERIC_BLOCKER_TERMS = {
    "auth",
    "coverage",
    "data",
    "error",
    "exception",
    "failure",
    "incident",
    "migration",
    "privacy",
    "production",
    "race",
    "rollback",
    "security",
    "test",
    "tests",
}
_GENERIC_COMMENT_TERMS = {
    "boundary",
    "clarity",
    "docs",
    "documentation",
    "format",
    "name",
    "naming",
    "readability",
    "refactor",
    "style",
}


class BaselineDefinition(BaseModel):
    """Human-readable definition of a deterministic review baseline."""

    name: BaselineName
    description: str
    unavailable_when: str


class BaselineEvaluation(BaseModel):
    """A baseline prediction plus agreement metrics against a held-out review."""

    name: BaselineName
    status: Literal["available", "unavailable"]
    selection: ReviewSelection | None = None
    agreement: ReviewAgreement | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class ReviewBaselineContext:
    """Input available to non-LLM baselines for one review turn."""

    prompt: str
    expectation: HeldOutReviewExpectation
    reference_answer: str = ""
    rubric_terms: list[str] = field(default_factory=list)


BASELINE_DEFINITIONS: tuple[BaselineDefinition, ...] = (
    BaselineDefinition(
        name="generic_reviewer",
        description=(
            "Keyword-only generic reviewer. It selects common blocker classes "
            "such as tests, security, production risk, and error handling, plus "
            "common non-blocking style/readability comments. It does not use the "
            "subject's evidence or expected labels."
        ),
        unavailable_when="No held-out review candidate universe is present.",
    ),
    BaselineDefinition(
        name="retrieval_only_similarity",
        description=(
            "Prompt-only lexical similarity baseline. It ranks fixed candidate "
            "summaries by token overlap with the review prompt and predicts the "
            "highest-overlap candidates above a small deterministic threshold. "
            "It does not call an LLM and does not read expected labels."
        ),
        unavailable_when="No held-out review candidate universe is present.",
    ),
)


def _tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in _TOKEN_RE.findall(text)
        if token.lower() not in _STOPWORDS and len(token) > 2
    }


def _candidate_terms(candidate: ReviewCandidate) -> set[str]:
    return _tokens(f"{candidate.id} {candidate.summary}")


def _has_candidates(expectation: HeldOutReviewExpectation) -> bool:
    return bool(expectation.blocker_candidates or expectation.comment_candidates)


def _selection_status(selection: ReviewSelection) -> str:
    if selection.selected_blocker_ids:
        return "request_changes"
    if selection.selected_comment_ids:
        return "comment"
    return "approve"


def _evaluate_baseline(
    name: BaselineName,
    context: ReviewBaselineContext,
    selection: ReviewSelection,
) -> BaselineEvaluation:
    selection.predicted_verdict = _selection_status(selection)
    return BaselineEvaluation(
        name=name,
        status="available",
        selection=selection,
        agreement=compute_review_agreement(context.expectation, selection),
    )


def run_generic_reviewer_baseline(
    context: ReviewBaselineContext,
) -> BaselineEvaluation:
    """Run the generic-reviewer keyword baseline for a review turn."""
    if not _has_candidates(context.expectation):
        return BaselineEvaluation(
            name="generic_reviewer",
            status="unavailable",
            unavailable_reason="No held-out review candidates to score.",
        )

    selected_blockers = [
        candidate.id
        for candidate in context.expectation.blocker_candidates
        if _candidate_terms(candidate) & _GENERIC_BLOCKER_TERMS
    ]
    selected_comments = [
        candidate.id
        for candidate in context.expectation.comment_candidates
        if _candidate_terms(candidate) & _GENERIC_COMMENT_TERMS
    ]

    selection = ReviewSelection(
        selected_blocker_ids=selected_blockers,
        selected_comment_ids=selected_comments,
        rationale=(
            "Selected candidates matching common generic review keywords; "
            "subject-specific evidence was not used."
        ),
    )
    return _evaluate_baseline("generic_reviewer", context, selection)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _select_by_similarity(
    query_terms: set[str],
    candidates: list[ReviewCandidate],
    threshold: float,
) -> list[str]:
    scored = [
        (candidate.id, _jaccard(query_terms, _candidate_terms(candidate)))
        for candidate in candidates
    ]
    selected = [candidate_id for candidate_id, score in scored if score >= threshold]
    if selected:
        return selected

    top = max(scored, key=lambda item: item[1], default=("", 0.0))
    if top[1] > 0.0:
        return [top[0]]
    return []


def run_retrieval_only_similarity_baseline(
    context: ReviewBaselineContext,
) -> BaselineEvaluation:
    """Run a deterministic prompt-similarity baseline for a review turn."""
    if not _has_candidates(context.expectation):
        return BaselineEvaluation(
            name="retrieval_only_similarity",
            status="unavailable",
            unavailable_reason="No held-out review candidates to score.",
        )

    query_terms = _tokens(context.prompt)
    selected_blockers = _select_by_similarity(
        query_terms,
        context.expectation.blocker_candidates,
        threshold=0.08,
    )
    selected_comments = _select_by_similarity(
        query_terms,
        context.expectation.comment_candidates,
        threshold=0.08,
    )

    selection = ReviewSelection(
        selected_blocker_ids=selected_blockers,
        selected_comment_ids=selected_comments,
        rationale=(
            "Selected candidates by lexical overlap with the prompt only; "
            "expected labels and LLM judging were not used."
        ),
    )
    return _evaluate_baseline("retrieval_only_similarity", context, selection)


def run_review_baselines(context: ReviewBaselineContext) -> list[BaselineEvaluation]:
    """Run all deterministic review baselines for one held-out review case."""
    return [
        run_generic_reviewer_baseline(context),
        run_retrieval_only_similarity_baseline(context),
    ]
