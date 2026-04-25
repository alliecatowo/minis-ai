"""Unit tests for eval/report.py render and JSON output."""

from __future__ import annotations

from eval.judge import RubricScore, ScoreCard, SubjectSummary, TurnScore
from eval.report import render_report, report_to_json
from eval.review import HeldOutReviewExpectation, ReviewSelection, compute_review_agreement
from eval.runner import EvalReport


def _turn_score(turn_id: str = "t1") -> TurnScore:
    return TurnScore(
        subject="testuser",
        turn_id=turn_id,
        prompt="prompt",
        reference_answer="reference",
        mini_response="response",
        case_type="adversarial",
        scorecard=ScoreCard(
            overall_score=4,
            voice_match=4,
            factual_accuracy=3,
            framework_consistency=5,
            recency_bias_penalty=0.25,
            overall_rationale="Solid response with minor misses.",
            rubric_scores=[
                RubricScore(criterion="framework_consistency", score=5, rationale="good"),
            ],
        ),
    )


def test_render_report_includes_new_dimensions() -> None:
    summary = SubjectSummary(subject="testuser", turn_scores=[_turn_score()])
    report = EvalReport(summaries=[summary], base_url="http://localhost:8000")

    md = render_report(report)

    assert "Avg Framework" in md
    assert "Avg Recency Bias" in md
    assert "Framework" in md
    assert "Recency Bias" in md
    assert "Recency Bias Penalty" in md


def test_report_to_json_includes_new_dimensions() -> None:
    summary = SubjectSummary(subject="testuser", turn_scores=[_turn_score()])
    report = EvalReport(summaries=[summary], base_url="http://localhost:8000")

    payload = report_to_json(report)

    subject = payload["subjects"][0]
    turn = subject["turns"][0]
    assert subject["avg_framework_consistency"] == 5.0
    assert subject["avg_recency_bias_penalty"] == 0.25
    assert subject["adversarial_turn_count"] == 1
    assert subject["non_adversarial_turn_count"] == 0
    assert subject["adversarial_pass_count"] == 1
    assert subject["adversarial_fail_count"] == 0
    assert subject["adversarial_pass_rate"] == 1.0
    assert subject["non_adversarial_pass_rate"] == 0.0
    assert turn["scorecard"]["framework_consistency"] == 5
    assert turn["scorecard"]["recency_bias_penalty"] == 0.25
    assert turn["case_type"] == "adversarial"


def test_render_report_includes_adversarial_summary_lines() -> None:
    summary = SubjectSummary(subject="testuser", turn_scores=[_turn_score(), _turn_score("t2")])
    report = EvalReport(summaries=[summary], base_url="http://localhost:8000")

    md = render_report(report)

    assert "Adversarial Cases" in md
    assert "pass: 2/2" in md
    assert "Adversarial Turns" in md
    assert "Adversarial Pass" in md


def test_report_includes_proof_grade_review_metrics() -> None:
    expectation = HeldOutReviewExpectation.from_dict(
        {
            "verdict": "comment",
            "expected_confidence": 0.75,
            "comment_candidates": [
                {
                    "id": "audience_translation",
                    "summary": "Translate implementation detail for the target audience.",
                    "expected": True,
                    "private_expected": True,
                    "expected_rank": 1,
                },
                {
                    "id": "risk_summary",
                    "summary": "Summarize residual risk.",
                    "expected": True,
                    "private_expected": True,
                    "expected_rank": 2,
                },
            ],
        }
    )
    scorecard = ScoreCard(
        overall_score=4,
        voice_match=4,
        factual_accuracy=4,
        framework_consistency=4,
        recency_bias_penalty=0.0,
        overall_rationale="Good review prediction.",
        review_selection=ReviewSelection(
            predicted_verdict="comment",
            selected_comment_ids=["audience_translation", "risk_summary"],
            confidence=0.70,
        ),
    )
    turn = TurnScore(
        subject="testuser",
        turn_id="audience_transfer_review",
        prompt="prompt",
        reference_answer="reference",
        mini_response="response",
        scorecard=scorecard,
        review_agreement=compute_review_agreement(
            expectation,
            scorecard.review_selection,
        ),
        audience_transfer=True,
    )
    summary = SubjectSummary(subject="testuser", turn_scores=[turn])
    report = EvalReport(summaries=[summary], base_url="http://localhost:8000")

    md = render_report(report)
    payload = report_to_json(report)

    assert "Proof Metrics" in md
    assert "Private-vs-expressed F1" in md
    assert "Audience Transfer" in md
    subject = payload["subjects"][0]
    assert subject["avg_private_f1"] == 1.0
    assert subject["avg_expressed_order_score"] == 1.0
    assert round(subject["avg_confidence_error"], 2) == 0.05
    assert subject["audience_transfer_turn_count"] == 1
    assert payload["baseline_definitions"]
