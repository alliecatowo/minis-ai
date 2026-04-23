"""Unit tests for eval/report.py render and JSON output."""

from __future__ import annotations

from eval.judge import RubricScore, ScoreCard, SubjectSummary, TurnScore
from eval.report import render_report, report_to_json
from eval.runner import EvalReport


def _turn_score(turn_id: str = "t1") -> TurnScore:
    return TurnScore(
        subject="testuser",
        turn_id=turn_id,
        prompt="prompt",
        reference_answer="reference",
        mini_response="response",
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
    assert turn["scorecard"]["framework_consistency"] == 5
    assert turn["scorecard"]["recency_bias_penalty"] == 0.25
