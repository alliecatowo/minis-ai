"""Unit tests for app.synthesis.framework_views.

Covers:
- _format_decision_framework: field extraction, badge logic
- format_decision_frameworks: sorting, filtering, limiting
- Edge cases: missing fields, empty payloads, malformed data
"""

from __future__ import annotations

from app.synthesis.framework_views import _format_decision_framework, format_decision_frameworks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raw_fw(
    framework_id: str = "framework:test",
    condition: str = "when X happens",
    decision_order: list[str] | None = None,
    value_ids: list[str] | None = None,
    tradeoff: str = "",
    confidence: float = 0.5,
    revision: int = 0,
) -> dict:
    return {
        "framework_id": framework_id,
        "condition": condition,
        "decision_order": decision_order if decision_order is not None else [condition],
        "value_ids": value_ids if value_ids is not None else ["value:correctness"],
        "tradeoff": tradeoff,
        "confidence": confidence,
        "revision": revision,
    }


def _p_json(frameworks: list[dict]) -> dict:
    return {
        "principles": [],
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": frameworks,
        },
    }


# ---------------------------------------------------------------------------
# _format_decision_framework
# ---------------------------------------------------------------------------


class TestFormatDecisionFramework:
    def test_extracts_all_canonical_fields(self):
        fw = _raw_fw(
            framework_id="framework:tests-before-merge",
            condition="PR contains untested public surface",
            decision_order=["block until unit tests added"],
            value_ids=["value:reliability"],
            confidence=0.82,
            revision=3,
        )
        result = _format_decision_framework(fw)
        assert result["framework_id"] == "framework:tests-before-merge"
        assert result["trigger"] == "PR contains untested public surface"
        assert result["action"] == "block until unit tests added"
        assert result["value"] == "reliability"
        assert result["confidence"] == 0.82
        assert result["revision"] == 3

    def test_badge_high_confidence(self):
        result = _format_decision_framework(_raw_fw(confidence=0.71))
        assert result["badge"] == "HIGH CONFIDENCE"

    def test_badge_exact_threshold(self):
        """Exactly 0.7 is HIGH CONFIDENCE (>= threshold)."""
        result = _format_decision_framework(_raw_fw(confidence=0.7))
        assert result["badge"] == "HIGH CONFIDENCE"

    def test_badge_low_confidence(self):
        result = _format_decision_framework(_raw_fw(confidence=0.25))
        assert result["badge"] == "LOW CONFIDENCE"

    def test_badge_below_threshold_boundary(self):
        """Exactly 0.3 is not LOW CONFIDENCE (threshold is <)."""
        result = _format_decision_framework(_raw_fw(confidence=0.3))
        assert result["badge"] == ""

    def test_badge_empty_for_medium(self):
        result = _format_decision_framework(_raw_fw(confidence=0.5))
        assert result["badge"] == ""

    def test_value_id_prefix_stripped(self):
        fw = _raw_fw(value_ids=["value:code_quality"])
        result = _format_decision_framework(fw)
        assert result["value"] == "code quality"

    def test_value_id_no_prefix(self):
        fw = _raw_fw(value_ids=["simplicity"])
        result = _format_decision_framework(fw)
        assert result["value"] == "simplicity"

    def test_action_falls_back_to_tradeoff(self):
        fw = _raw_fw(decision_order=[], tradeoff="prioritise correctness over speed")
        result = _format_decision_framework(fw)
        assert result["action"] == "prioritise correctness over speed"

    def test_empty_decision_order_uses_tradeoff(self):
        fw = _raw_fw(decision_order=[], tradeoff="fallback tradeoff")
        result = _format_decision_framework(fw)
        assert result["action"] == "fallback tradeoff"

    def test_missing_condition_returns_empty_trigger(self):
        fw = {"framework_id": "fw:x", "confidence": 0.5}
        result = _format_decision_framework(fw)
        assert result["trigger"] == ""

    def test_missing_value_ids_returns_empty_value(self):
        fw = {"framework_id": "fw:x", "confidence": 0.5, "value_ids": []}
        result = _format_decision_framework(fw)
        assert result["value"] == ""

    def test_confidence_coerced_from_string(self):
        fw = _raw_fw(confidence=0.5)
        fw["confidence"] = "0.75"
        result = _format_decision_framework(fw)
        assert result["confidence"] == 0.75

    def test_revision_coerced_from_string(self):
        fw = _raw_fw()
        fw["revision"] = "4"
        result = _format_decision_framework(fw)
        assert result["revision"] == 4

    def test_invalid_confidence_defaults_to_half(self):
        fw = _raw_fw()
        fw["confidence"] = "not-a-number"
        result = _format_decision_framework(fw)
        assert result["confidence"] == 0.5

    def test_invalid_revision_defaults_to_zero(self):
        fw = _raw_fw()
        fw["revision"] = None
        result = _format_decision_framework(fw)
        assert result["revision"] == 0

    def test_confidence_rounded_to_four_decimals(self):
        fw = _raw_fw(confidence=0.123456789)
        result = _format_decision_framework(fw)
        assert result["confidence"] == round(0.123456789, 4)


# ---------------------------------------------------------------------------
# format_decision_frameworks
# ---------------------------------------------------------------------------


class TestFormatDecisionFrameworks:
    def test_returns_empty_for_none(self):
        assert format_decision_frameworks(None) == []

    def test_returns_empty_for_missing_decision_frameworks_key(self):
        assert format_decision_frameworks({"principles": []}) == []

    def test_returns_empty_for_empty_frameworks_list(self):
        p = _p_json([])
        assert format_decision_frameworks(p) == []

    def test_sorted_by_confidence_desc(self):
        fws = [
            _raw_fw("fw:a", confidence=0.4),
            _raw_fw("fw:b", confidence=0.9),
            _raw_fw("fw:c", confidence=0.6),
        ]
        result = format_decision_frameworks(_p_json(fws))
        ids = [r["framework_id"] for r in result]
        assert ids == ["fw:b", "fw:c", "fw:a"]

    def test_tiebreak_by_revision_desc(self):
        fws = [
            _raw_fw("fw:low-rev", confidence=0.6, revision=1),
            _raw_fw("fw:high-rev", confidence=0.6, revision=5),
        ]
        result = format_decision_frameworks(_p_json(fws))
        assert result[0]["framework_id"] == "fw:high-rev"
        assert result[1]["framework_id"] == "fw:low-rev"

    def test_min_confidence_filter(self):
        fws = [
            _raw_fw("fw:keep", confidence=0.8),
            _raw_fw("fw:drop", confidence=0.2),
        ]
        result = format_decision_frameworks(_p_json(fws), min_confidence=0.5)
        assert len(result) == 1
        assert result[0]["framework_id"] == "fw:keep"

    def test_min_confidence_zero_returns_all(self):
        fws = [_raw_fw(f"fw:{i}", confidence=float(i) / 10) for i in range(5)]
        result = format_decision_frameworks(_p_json(fws), min_confidence=0.0)
        assert len(result) == 5

    def test_limit_applied(self):
        fws = [_raw_fw(f"fw:{i}", confidence=float(i) / 20) for i in range(15)]
        result = format_decision_frameworks(_p_json(fws), limit=4)
        assert len(result) == 4

    def test_limit_default_is_ten(self):
        fws = [_raw_fw(f"fw:{i}", confidence=float(i) / 20) for i in range(15)]
        result = format_decision_frameworks(_p_json(fws))
        assert len(result) == 10

    def test_result_has_canonical_shape(self):
        fw = _raw_fw("fw:shape-check", condition="cond", confidence=0.75, revision=1)
        result = format_decision_frameworks(_p_json([fw]))
        assert len(result) == 1
        item = result[0]
        for key in ("framework_id", "trigger", "action", "value", "confidence", "revision", "badge"):
            assert key in item

    def test_skips_non_dict_entries_in_list(self):
        p = _p_json([_raw_fw("fw:valid")])
        p["decision_frameworks"]["frameworks"].append("not-a-dict")  # type: ignore[arg-type]
        result = format_decision_frameworks(p)
        assert all(isinstance(r, dict) for r in result)
        assert len(result) == 1

    def test_badge_field_values_are_correct(self):
        fws = [
            _raw_fw("fw:high", confidence=0.8),
            _raw_fw("fw:mid", confidence=0.5),
            _raw_fw("fw:low", confidence=0.1),
        ]
        result = format_decision_frameworks(_p_json(fws))
        badges = {r["framework_id"]: r["badge"] for r in result}
        assert badges["fw:high"] == "HIGH CONFIDENCE"
        assert badges["fw:mid"] == ""
        assert badges["fw:low"] == "LOW CONFIDENCE"
