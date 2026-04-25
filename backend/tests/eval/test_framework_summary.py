"""Unit tests for eval/judge.py compute_framework_summary."""

from __future__ import annotations

import pytest

from eval.judge import compute_framework_summary


class TestComputeFrameworkSummary:
    def test_empty_list_returns_zero_metrics(self) -> None:
        result = compute_framework_summary([])
        assert result["total"] == 0
        assert result["mean_confidence"] == 0.0
        assert result["max_revision"] == 0
        assert result["high_band_count"] == 0
        assert result["low_band_count"] == 0

    def test_total_equals_list_length(self) -> None:
        frameworks = [
            {"confidence": 0.8, "revision": 1},
            {"confidence": 0.5, "revision": 2},
            {"confidence": 0.3, "revision": 0},
        ]
        result = compute_framework_summary(frameworks)
        assert result["total"] == 3

    def test_mean_confidence_computed_correctly(self) -> None:
        frameworks = [
            {"confidence": 0.6, "revision": 0},
            {"confidence": 0.8, "revision": 0},
            {"confidence": 1.0, "revision": 0},
        ]
        result = compute_framework_summary(frameworks)
        assert result["mean_confidence"] == pytest.approx(0.8)

    def test_max_revision_is_highest(self) -> None:
        frameworks = [
            {"confidence": 0.5, "revision": 3},
            {"confidence": 0.5, "revision": 7},
            {"confidence": 0.5, "revision": 1},
        ]
        result = compute_framework_summary(frameworks)
        assert result["max_revision"] == 7

    def test_high_band_count_gte_0_7(self) -> None:
        frameworks = [
            {"confidence": 0.7, "revision": 0},   # boundary — counts
            {"confidence": 0.9, "revision": 0},   # high
            {"confidence": 0.69, "revision": 0},  # just below
            {"confidence": 0.3, "revision": 0},   # low
        ]
        result = compute_framework_summary(frameworks)
        assert result["high_band_count"] == 2

    def test_low_band_count_lt_0_4(self) -> None:
        frameworks = [
            {"confidence": 0.39, "revision": 0},  # just below — counts
            {"confidence": 0.1, "revision": 0},   # low
            {"confidence": 0.4, "revision": 0},   # boundary — does NOT count
            {"confidence": 0.8, "revision": 0},   # high
        ]
        result = compute_framework_summary(frameworks)
        assert result["low_band_count"] == 2

    def test_missing_confidence_defaults_to_zero(self) -> None:
        frameworks = [{"revision": 1}, {"confidence": 0.9, "revision": 0}]
        result = compute_framework_summary(frameworks)
        assert result["total"] == 2
        assert result["mean_confidence"] == pytest.approx(0.45)
        # The missing-confidence entry (0.0) is below 0.4
        assert result["low_band_count"] == 1

    def test_missing_revision_defaults_to_zero(self) -> None:
        frameworks = [{"confidence": 0.8}, {"confidence": 0.5, "revision": 5}]
        result = compute_framework_summary(frameworks)
        assert result["max_revision"] == 5

    def test_single_framework(self) -> None:
        frameworks = [{"confidence": 0.75, "revision": 2}]
        result = compute_framework_summary(frameworks)
        assert result["total"] == 1
        assert result["mean_confidence"] == pytest.approx(0.75)
        assert result["max_revision"] == 2
        assert result["high_band_count"] == 1
        assert result["low_band_count"] == 0

    def test_all_high_band(self) -> None:
        frameworks = [{"confidence": 0.8, "revision": 1}] * 5
        result = compute_framework_summary(frameworks)
        assert result["high_band_count"] == 5
        assert result["low_band_count"] == 0

    def test_all_low_band(self) -> None:
        frameworks = [{"confidence": 0.2, "revision": 0}] * 4
        result = compute_framework_summary(frameworks)
        assert result["high_band_count"] == 0
        assert result["low_band_count"] == 4
