"""Unit tests for decision-framework regression detection in eval/report.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.judge import ScoreCard, SubjectSummary, TurnScore
from eval.report import render_report, report_to_json, _framework_regression_lines
from eval.runner import EvalReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
            framework_consistency=4,
            recency_bias_penalty=0.1,
            overall_rationale="Decent.",
            rubric_scores=[],
        ),
    )


def _summary(
    subject: str = "testuser",
    fw_summary: dict | None = None,
) -> SubjectSummary:
    s = SubjectSummary(subject=subject, turn_scores=[_turn_score()])
    s.decision_frameworks_summary = fw_summary
    return s


def _report(summaries: list[SubjectSummary]) -> EvalReport:
    return EvalReport(summaries=summaries, base_url="http://localhost:8000")


def _prior_json(
    subjects: list[dict],
    overall_avg: float = 4.0,
) -> dict:
    return {"overall_avg": overall_avg, "subjects": subjects}


# ---------------------------------------------------------------------------
# _framework_regression_lines unit tests
# ---------------------------------------------------------------------------


class TestFrameworkRegressionLines:
    def test_no_regression_when_both_none(self) -> None:
        report = _report([_summary("alice", fw_summary=None)])
        prior = [{"subject": "alice", "decision_frameworks_summary": None}]
        lines = _framework_regression_lines(report, prior)
        assert lines == []

    def test_no_regression_when_prior_none(self) -> None:
        cur_fw = {"total": 10, "mean_confidence": 0.8, "max_revision": 3, "high_band_count": 7, "low_band_count": 1}
        report = _report([_summary("alice", fw_summary=cur_fw)])
        prior = [{"subject": "alice", "decision_frameworks_summary": None}]
        lines = _framework_regression_lines(report, prior)
        assert lines == []

    def test_no_regression_when_current_none(self) -> None:
        prev_fw = {"total": 10, "mean_confidence": 0.8, "max_revision": 3, "high_band_count": 7, "low_band_count": 1}
        report = _report([_summary("alice", fw_summary=None)])
        prior = [{"subject": "alice", "decision_frameworks_summary": prev_fw}]
        lines = _framework_regression_lines(report, prior)
        assert lines == []

    def test_total_regression_fires_when_drop_gt_1(self) -> None:
        cur_fw = {"total": 7, "mean_confidence": 0.8, "max_revision": 3, "high_band_count": 5, "low_band_count": 0}
        prev_fw = {"total": 10, "mean_confidence": 0.8, "max_revision": 3, "high_band_count": 5, "low_band_count": 0}
        report = _report([_summary("alice", fw_summary=cur_fw)])
        prior = [{"subject": "alice", "decision_frameworks_summary": prev_fw}]
        lines = _framework_regression_lines(report, prior)
        assert any("total" in line for line in lines)
        assert any("alice" in line for line in lines)

    def test_total_regression_does_not_fire_when_drop_eq_1(self) -> None:
        cur_fw = {"total": 9, "mean_confidence": 0.8, "max_revision": 3, "high_band_count": 5, "low_band_count": 0}
        prev_fw = {"total": 10, "mean_confidence": 0.8, "max_revision": 3, "high_band_count": 5, "low_band_count": 0}
        report = _report([_summary("alice", fw_summary=cur_fw)])
        prior = [{"subject": "alice", "decision_frameworks_summary": prev_fw}]
        lines = _framework_regression_lines(report, prior)
        # No subject warning because drop is exactly 1 (threshold is *> 1*)
        assert not any("total" in line for line in lines if "Framework" not in line)

    def test_mean_confidence_regression_fires_when_drop_gt_0_05(self) -> None:
        cur_fw = {"total": 10, "mean_confidence": 0.70, "max_revision": 2, "high_band_count": 5, "low_band_count": 0}
        prev_fw = {"total": 10, "mean_confidence": 0.76, "max_revision": 2, "high_band_count": 5, "low_band_count": 0}
        report = _report([_summary("alice", fw_summary=cur_fw)])
        prior = [{"subject": "alice", "decision_frameworks_summary": prev_fw}]
        lines = _framework_regression_lines(report, prior)
        assert any("mean_confidence" in line for line in lines)

    def test_mean_confidence_regression_does_not_fire_when_drop_lt_threshold(self) -> None:
        # Drop of 0.04 is below the 0.05 threshold — should not fire.
        cur_fw = {"total": 10, "mean_confidence": 0.76, "max_revision": 2, "high_band_count": 5, "low_band_count": 0}
        prev_fw = {"total": 10, "mean_confidence": 0.80, "max_revision": 2, "high_band_count": 5, "low_band_count": 0}
        report = _report([_summary("alice", fw_summary=cur_fw)])
        prior = [{"subject": "alice", "decision_frameworks_summary": prev_fw}]
        lines = _framework_regression_lines(report, prior)
        assert not any("mean_confidence" in line for line in lines)

    def test_high_band_regression_fires_when_drop_gt_1(self) -> None:
        cur_fw = {"total": 10, "mean_confidence": 0.8, "max_revision": 2, "high_band_count": 3, "low_band_count": 0}
        prev_fw = {"total": 10, "mean_confidence": 0.8, "max_revision": 2, "high_band_count": 6, "low_band_count": 0}
        report = _report([_summary("alice", fw_summary=cur_fw)])
        prior = [{"subject": "alice", "decision_frameworks_summary": prev_fw}]
        lines = _framework_regression_lines(report, prior)
        assert any("high_band_count" in line for line in lines)

    def test_high_band_regression_does_not_fire_when_drop_eq_1(self) -> None:
        cur_fw = {"total": 10, "mean_confidence": 0.8, "max_revision": 2, "high_band_count": 5, "low_band_count": 0}
        prev_fw = {"total": 10, "mean_confidence": 0.8, "max_revision": 2, "high_band_count": 6, "low_band_count": 0}
        report = _report([_summary("alice", fw_summary=cur_fw)])
        prior = [{"subject": "alice", "decision_frameworks_summary": prev_fw}]
        lines = _framework_regression_lines(report, prior)
        assert not any("high_band_count" in line for line in lines)

    def test_improvement_does_not_produce_warnings(self) -> None:
        cur_fw = {"total": 15, "mean_confidence": 0.9, "max_revision": 5, "high_band_count": 12, "low_band_count": 0}
        prev_fw = {"total": 10, "mean_confidence": 0.7, "max_revision": 2, "high_band_count": 5, "low_band_count": 2}
        report = _report([_summary("alice", fw_summary=cur_fw)])
        prior = [{"subject": "alice", "decision_frameworks_summary": prev_fw}]
        lines = _framework_regression_lines(report, prior)
        # No warnings for improvements
        assert lines == []

    def test_multiple_subjects_each_checked_independently(self) -> None:
        cur_fw_alice = {"total": 5, "mean_confidence": 0.5, "max_revision": 1, "high_band_count": 2, "low_band_count": 1}
        prev_fw_alice = {"total": 10, "mean_confidence": 0.5, "max_revision": 1, "high_band_count": 2, "low_band_count": 1}
        cur_fw_bob = {"total": 8, "mean_confidence": 0.8, "max_revision": 2, "high_band_count": 5, "low_band_count": 0}
        prev_fw_bob = {"total": 8, "mean_confidence": 0.8, "max_revision": 2, "high_band_count": 5, "low_band_count": 0}

        report = _report([
            _summary("alice", fw_summary=cur_fw_alice),
            _summary("bob", fw_summary=cur_fw_bob),
        ])
        prior = [
            {"subject": "alice", "decision_frameworks_summary": prev_fw_alice},
            {"subject": "bob", "decision_frameworks_summary": prev_fw_bob},
        ]
        lines = _framework_regression_lines(report, prior)
        # Alice regressed; bob didn't
        combined = "\n".join(lines)
        assert "alice" in combined
        assert "bob" not in combined

    def test_heading_included_when_regressions_present(self) -> None:
        cur_fw = {"total": 5, "mean_confidence": 0.5, "max_revision": 1, "high_band_count": 2, "low_band_count": 1}
        prev_fw = {"total": 10, "mean_confidence": 0.5, "max_revision": 1, "high_band_count": 2, "low_band_count": 1}
        report = _report([_summary("alice", fw_summary=cur_fw)])
        prior = [{"subject": "alice", "decision_frameworks_summary": prev_fw}]
        lines = _framework_regression_lines(report, prior)
        assert any("Framework regressions" in line for line in lines)

    def test_heading_not_included_when_no_regressions(self) -> None:
        cur_fw = {"total": 10, "mean_confidence": 0.8, "max_revision": 3, "high_band_count": 7, "low_band_count": 0}
        prev_fw = {"total": 10, "mean_confidence": 0.8, "max_revision": 3, "high_band_count": 7, "low_band_count": 0}
        report = _report([_summary("alice", fw_summary=cur_fw)])
        prior = [{"subject": "alice", "decision_frameworks_summary": prev_fw}]
        lines = _framework_regression_lines(report, prior)
        assert lines == []


# ---------------------------------------------------------------------------
# Integration: render_report includes framework regressions in prior block
# ---------------------------------------------------------------------------


class TestRenderReportFrameworkRegressions:
    def test_framework_regressions_appear_in_markdown(self, tmp_path: Path) -> None:
        cur_fw = {"total": 5, "mean_confidence": 0.60, "max_revision": 1, "high_band_count": 2, "low_band_count": 1}
        prev_fw = {"total": 10, "mean_confidence": 0.80, "max_revision": 2, "high_band_count": 7, "low_band_count": 0}

        summary = _summary("testuser", fw_summary=cur_fw)
        report = _report([summary])

        prior_data = _prior_json(
            subjects=[{"subject": "testuser", "decision_frameworks_summary": prev_fw}],
            overall_avg=report.overall_avg(),
        )
        prior_path = tmp_path / "prior.json"
        prior_path.write_text(json.dumps(prior_data))

        md = render_report(report, prior_report_path=prior_path)

        assert "Framework regressions" in md
        assert "testuser" in md

    def test_framework_summary_rendered_per_subject(self) -> None:
        fw = {"total": 12, "mean_confidence": 0.75, "max_revision": 4, "high_band_count": 9, "low_band_count": 1}
        summary = _summary("testuser", fw_summary=fw)
        report = _report([summary])

        md = render_report(report)

        assert "Decision Frameworks" in md
        assert "12" in md  # total
        assert "0.750" in md  # mean_confidence

    def test_no_frameworks_shows_placeholder(self) -> None:
        summary = _summary("testuser", fw_summary=None)
        report = _report([summary])

        md = render_report(report)

        assert "Decision frameworks: not available" in md

    def test_report_to_json_includes_framework_summary(self) -> None:
        fw = {"total": 8, "mean_confidence": 0.72, "max_revision": 3, "high_band_count": 5, "low_band_count": 1}
        summary = _summary("testuser", fw_summary=fw)
        report = _report([summary])

        payload = report_to_json(report)
        subject = payload["subjects"][0]

        assert "decision_frameworks_summary" in subject
        assert subject["decision_frameworks_summary"]["total"] == 8
        assert subject["decision_frameworks_summary"]["mean_confidence"] == pytest.approx(0.72)

    def test_report_to_json_framework_summary_none(self) -> None:
        summary = _summary("testuser", fw_summary=None)
        report = _report([summary])

        payload = report_to_json(report)
        subject = payload["subjects"][0]

        assert subject["decision_frameworks_summary"] is None
