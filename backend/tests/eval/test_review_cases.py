from __future__ import annotations

from pathlib import Path

import pytest

from eval.review import compute_review_agreement
from eval.review_cases import (
    GoldReviewCaseFile,
    GoldReviewCaseInput,
    GoldTargetAudience,
    GoldAssessmentSignal,
    GoldPrivateAssessment,
    GoldExpressedFeedback,
    GoldEvidenceReference,
    GoldReviewCase,
    GoldScoringDimension,
)
from eval.runner import GoldenTurn


def _fixture_path() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "eval"
        / "gold_review_cases"
        / "alliecatowo.yaml"
    )


def test_checked_in_gold_review_cases_cover_required_representatives() -> None:
    fixture = GoldReviewCaseFile.from_yaml(_fixture_path())

    assert fixture.subject == "alliecatowo"
    assert {case.case_type for case in fixture.cases} == {
        "architecture_domain_boundary",
        "pragmatic_shipping_tradeoff",
        "audience_context_sensitive_suppression",
        "recency_vs_durable_framework",
        "novel_work_generalization",
    }


def test_checked_in_gold_review_cases_have_required_schema_support() -> None:
    fixture = GoldReviewCaseFile.from_yaml(_fixture_path())

    for case in fixture.cases:
        assert case.target_audience.notes
        assert case.evidence_references
        assert case.expected_private_assessment.confidence > 0
        assert case.expected_private_assessment.blocking_issues or case.expected_private_assessment.non_blocking_issues
        assert case.expected_expressed_feedback.summary
        assert case.scoring_dimensions
        assert sum(dimension.weight for dimension in case.scoring_dimensions) == pytest.approx(1.0)


def test_audience_suppression_case_keeps_private_signal_out_of_expressed_feedback() -> None:
    fixture = GoldReviewCaseFile.from_yaml(_fixture_path())
    case = next(c for c in fixture.cases if c.id == "junior_audience_suppression")

    private_keys = {signal.key for signal in case.private_signals}
    expressed_keys = {
        comment.issue_key
        for comment in case.expected_expressed_feedback.comments
        if comment.issue_key
    }

    assert "vague-helper-name" in private_keys
    assert "vague-helper-name" in case.expected_expressed_feedback.suppressed_private_signal_keys
    assert "vague-helper-name" not in expressed_keys


def test_gold_case_converts_to_existing_held_out_review_expectation() -> None:
    fixture = GoldReviewCaseFile.from_yaml(_fixture_path())
    case = next(c for c in fixture.cases if c.id == "architecture_domain_boundary_pr")

    expectation = case.to_held_out_review_expectation()

    assert expectation.verdict == "request_changes"
    assert expectation.expected_blocker_ids == [
        "domain-boundary-leak",
        "missing-ingestion-tests",
    ]
    assert expectation.expected_comment_ids == ["provenance-preservation"]


def test_gold_case_expectation_scores_against_existing_review_agreement() -> None:
    fixture = GoldReviewCaseFile.from_yaml(_fixture_path())
    case = next(c for c in fixture.cases if c.id == "novel_rust_cli_generalization")
    expectation = case.to_held_out_review_expectation()

    agreement = compute_review_agreement(expectation, selection=None)

    assert agreement.expected_verdict == "request_changes"
    assert agreement.predicted_verdict == "unclear"
    assert agreement.verdict_match is False
    assert agreement.blocker_recall == 0.0


def test_gold_case_can_be_adapted_for_existing_golden_turn_runner() -> None:
    fixture = GoldReviewCaseFile.from_yaml(_fixture_path())
    case = next(c for c in fixture.cases if c.id == "temporal_framework_payments_shortcut")

    turn = GoldenTurn.from_dict(case.to_golden_turn_dict())

    assert turn.id == case.id
    assert turn.case_type == "gold_review_case"
    assert "private_assessment" in turn.reference_answer
    assert turn.held_out_review is not None
    assert turn.held_out_review.expected_blocker_ids == [
        "durable-validation-policy",
        "provenance-loss-risk",
    ]


def test_gold_case_validation_rejects_unknown_evidence_reference() -> None:
    with pytest.raises(ValueError, match="Unknown evidence refs"):
        GoldReviewCase(
            id="bad",
            title="Bad case",
            case_type="architecture_domain_boundary",
            intent="Exercise validation.",
            target_audience=GoldTargetAudience(
                author_model="trusted_peer",
                delivery_context="normal",
                notes="Audience context.",
            ),
            input=GoldReviewCaseInput(
                title="A PR",
                author_model="trusted_peer",
                delivery_context="normal",
            ),
            expected_private_assessment=GoldPrivateAssessment(
                confidence=0.7,
                blocking_issues=[
                    GoldAssessmentSignal(
                        key="missing-tests",
                        summary="Missing tests.",
                        rationale="New behavior needs coverage.",
                        confidence=0.8,
                        evidence_refs=["missing-ref"],
                    )
                ],
            ),
            expected_expressed_feedback=GoldExpressedFeedback(
                approval_state="request_changes",
                summary="Request changes.",
            ),
            evidence_references=[
                GoldEvidenceReference(
                    id="ev-1",
                    source="docs/PROGRAM.md",
                    item_type="program_spec",
                    note="Ground truth infrastructure matters.",
                )
            ],
            scoring_dimensions=[
                GoldScoringDimension(
                    name="blocker_recall",
                    weight=1.0,
                    rubric="Catches blocker.",
                    expected_signal_keys=["missing-tests"],
                )
            ],
        )


def test_gold_case_validation_rejects_target_input_mismatch() -> None:
    with pytest.raises(ValueError, match="author_model must match"):
        GoldReviewCase(
            id="bad-audience",
            title="Bad audience",
            case_type="audience_context_sensitive_suppression",
            intent="Exercise validation.",
            target_audience=GoldTargetAudience(
                author_model="junior_peer",
                delivery_context="normal",
                notes="Junior audience.",
            ),
            input=GoldReviewCaseInput(
                title="A PR",
                author_model="senior_peer",
                delivery_context="normal",
            ),
            expected_private_assessment=GoldPrivateAssessment(
                confidence=0.7,
                blocking_issues=[
                    GoldAssessmentSignal(
                        key="missing-tests",
                        summary="Missing tests.",
                        rationale="New behavior needs coverage.",
                        confidence=0.8,
                        evidence_refs=["ev-1"],
                    )
                ],
            ),
            expected_expressed_feedback=GoldExpressedFeedback(
                approval_state="request_changes",
                summary="Request changes.",
            ),
            evidence_references=[
                GoldEvidenceReference(
                    id="ev-1",
                    source="docs/PROGRAM.md",
                    item_type="program_spec",
                    note="Ground truth infrastructure matters.",
                )
            ],
            scoring_dimensions=[
                GoldScoringDimension(
                    name="blocker_recall",
                    weight=1.0,
                    rubric="Catches blocker.",
                    expected_signal_keys=["missing-tests"],
                )
            ],
        )
