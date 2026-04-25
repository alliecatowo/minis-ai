"""Deterministic tests for review-prediction baselines and proof metrics."""

from __future__ import annotations

import pytest

from eval.baselines import ReviewBaselineContext, run_review_baselines
from eval.review import (
    HeldOutReviewExpectation,
    ReviewSelection,
    compute_review_agreement,
)


def _expectation() -> HeldOutReviewExpectation:
    return HeldOutReviewExpectation.from_dict(
        {
            "verdict": "request_changes",
            "audience_transfer": True,
            "expected_confidence": 0.8,
            "blocker_candidates": [
                {
                    "id": "missing_tests",
                    "summary": "The behavior needs regression test coverage.",
                    "expected": True,
                    "private_expected": True,
                    "should_surface": True,
                    "expected_rank": 1,
                    "expected_confidence": 0.9,
                },
                {
                    "id": "unsafe_exception",
                    "summary": "The code swallows production exceptions.",
                    "expected": False,
                    "private_expected": True,
                    "should_surface": False,
                },
            ],
            "comment_candidates": [
                {
                    "id": "clarity_pass",
                    "summary": "The boundary naming could be clearer.",
                    "expected": True,
                    "private_expected": True,
                    "should_surface": True,
                    "expected_rank": 2,
                    "expected_confidence": 0.7,
                }
            ],
        }
    )


def test_review_agreement_reports_private_order_and_calibration_metrics() -> None:
    agreement = compute_review_agreement(
        _expectation(),
        ReviewSelection(
            predicted_verdict="request_changes",
            selected_blocker_ids=["missing_tests"],
            selected_comment_ids=["clarity_pass"],
            confidence=0.7,
        ),
    )

    assert agreement.verdict_match is True
    assert agreement.private_precision == pytest.approx(1.0)
    assert agreement.private_recall == pytest.approx(2 / 3)
    assert agreement.private_f1 == pytest.approx(0.8)
    assert agreement.expressed_order_score == pytest.approx(1.0)
    assert agreement.confidence_error == pytest.approx(0.1)
    assert agreement.audience_transfer is True
    assert agreement.unavailable_metrics == []


def test_review_agreement_marks_unavailable_metrics_without_labels() -> None:
    expectation = HeldOutReviewExpectation.from_dict(
        {
            "verdict": "approve",
            "blocker_candidates": [],
            "comment_candidates": [
                {
                    "id": "rename",
                    "summary": "Rename helper for clarity.",
                    "expected": True,
                }
            ],
        }
    )

    agreement = compute_review_agreement(
        expectation,
        ReviewSelection(
            predicted_verdict="comment",
            selected_comment_ids=["rename"],
        ),
    )

    assert agreement.private_f1 is None
    assert agreement.confidence_error is None
    assert "private_vs_expressed" in agreement.unavailable_metrics
    assert "calibration_confidence" in agreement.unavailable_metrics


def test_review_baselines_are_deterministic_and_do_not_need_llm() -> None:
    context = ReviewBaselineContext(
        prompt="Please review a change adding behavior without tests.",
        expectation=_expectation(),
    )

    baselines = run_review_baselines(context)

    assert {baseline.name for baseline in baselines} == {
        "generic_reviewer",
        "retrieval_only_similarity",
    }
    assert all(baseline.status == "available" for baseline in baselines)
    generic = next(item for item in baselines if item.name == "generic_reviewer")
    assert generic.selection is not None
    assert "missing_tests" in generic.selection.selected_blocker_ids
    assert generic.agreement is not None
    assert generic.agreement.overall_agreement >= 0.0


def test_review_baselines_report_unavailable_without_candidate_universe() -> None:
    baselines = run_review_baselines(
        ReviewBaselineContext(
            prompt="Review this.",
            expectation=HeldOutReviewExpectation.from_dict(
                {"verdict": "approve", "blocker_candidates": [], "comment_candidates": []}
            ),
        )
    )

    assert all(baseline.status == "unavailable" for baseline in baselines)
    assert all(baseline.unavailable_reason for baseline in baselines)
