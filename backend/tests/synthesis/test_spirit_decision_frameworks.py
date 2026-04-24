"""Tests for spirit.py — decision-framework rendering consumed by build_system_prompt.

Covers:
- Legacy flat-principles shape only → identical output as today (back-compat)
- Both shapes present → only the framework rendering is included; no flat duplicate
- Confidence ranking + low-confidence filtering + badges
- Empty decision_frameworks → fallback to flat principles
- Stable ordering (deterministic tie-break on revision)
- None / missing principles_json → no DECISION FRAMEWORKS block
"""

from __future__ import annotations

from app.synthesis.spirit import _render_decision_frameworks, build_system_prompt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_framework(
    framework_id: str = "framework:test",
    condition: str = "When code review is requested",
    action: str = "Request changes",
    value_ids: list[str] | None = None,
    tradeoff: str = "Quality prioritized",
    confidence: float = 0.8,
    revision: int = 0,
) -> dict:
    return {
        "framework_id": framework_id,
        "condition": condition,
        "action": action,
        "value_ids": value_ids or ["value:code_quality"],
        "tradeoff": tradeoff,
        "confidence": confidence,
        "revision": revision,
        "decision_order": [condition],
        "priority": "high",
        "evidence_ids": ["ev-1", "ev-2", "ev-3", "ev-4", "ev-5"],
        "confidence_history": [],
    }


def _make_principles_json_with_frameworks(frameworks: list[dict]) -> dict:
    return {
        "principles": [
            {
                "trigger": "legacy trigger",
                "action": "legacy action",
                "value": "legacy value",
                "intensity": 0.7,
            }
        ],
        "decision_frameworks": {
            "frameworks": frameworks,
        },
    }


def _make_principles_json_flat_only() -> dict:
    return {
        "principles": [
            {
                "trigger": "flat trigger A",
                "action": "flat action A",
                "value": "flat value A",
                "intensity": 0.8,
            },
            {
                "trigger": "flat trigger B",
                "action": "flat action B",
                "value": "flat value B",
                "intensity": 0.6,
            },
        ]
    }


# ---------------------------------------------------------------------------
# _render_decision_frameworks unit tests
# ---------------------------------------------------------------------------


class TestRenderDecisionFrameworks:
    def test_returns_empty_string_for_none(self):
        assert _render_decision_frameworks(None) == ""

    def test_returns_empty_string_for_empty_dict(self):
        assert _render_decision_frameworks({}) == ""

    def test_returns_empty_string_when_no_decision_frameworks_key(self):
        assert _render_decision_frameworks({"principles": []}) == ""

    def test_returns_empty_string_when_frameworks_list_empty(self):
        pj = {"decision_frameworks": {"frameworks": []}}
        assert _render_decision_frameworks(pj) == ""

    def test_renders_high_confidence_badge(self):
        fw = _make_framework(confidence=0.85, revision=3)
        pj = _make_principles_json_with_frameworks([fw])
        result = _render_decision_frameworks(pj)
        assert "[HIGH CONFIDENCE ✓]" in result

    def test_no_high_confidence_badge_for_medium(self):
        fw = _make_framework(confidence=0.5, revision=0)
        pj = _make_principles_json_with_frameworks([fw])
        result = _render_decision_frameworks(pj)
        assert "[HIGH CONFIDENCE ✓]" not in result
        assert "[LOW CONFIDENCE ⚠" not in result

    def test_renders_validated_badge_when_revision_positive(self):
        fw = _make_framework(confidence=0.75, revision=2)
        pj = _make_principles_json_with_frameworks([fw])
        result = _render_decision_frameworks(pj)
        assert "[validated 2 times]" in result

    def test_validated_singular_for_revision_1(self):
        fw = _make_framework(confidence=0.75, revision=1)
        pj = _make_principles_json_with_frameworks([fw])
        result = _render_decision_frameworks(pj)
        assert "[validated 1 time]" in result

    def test_no_validated_badge_when_revision_zero(self):
        fw = _make_framework(confidence=0.75, revision=0)
        pj = _make_principles_json_with_frameworks([fw])
        result = _render_decision_frameworks(pj)
        assert "validated" not in result

    def test_filters_low_confidence_when_enough_high_confidence(self):
        """Frameworks with confidence < 0.3 are hidden when ≥3 high-conf items exist."""
        high_fws = [
            _make_framework(f"fw:{i}", confidence=0.8) for i in range(3)
        ]
        low_fw = _make_framework("fw:low", condition="Low confidence trigger", confidence=0.1)
        pj = _make_principles_json_with_frameworks(high_fws + [low_fw])
        result = _render_decision_frameworks(pj)
        assert "Low confidence trigger" not in result

    def test_includes_low_confidence_informational_when_few_high_conf(self):
        """When fewer than 3 high-conf frameworks, low-conf ones appear with annotation."""
        low_fw = _make_framework("fw:low", condition="Sparse trigger", confidence=0.1)
        pj = _make_principles_json_with_frameworks([low_fw])
        result = _render_decision_frameworks(pj)
        assert "Sparse trigger" in result
        assert "informational" in result.lower()

    def test_sorted_by_confidence_desc(self):
        fw_low = _make_framework("fw:low", condition="Low cond", confidence=0.4, revision=0)
        fw_high = _make_framework("fw:high", condition="High cond", confidence=0.9, revision=0)
        pj = _make_principles_json_with_frameworks([fw_low, fw_high])
        result = _render_decision_frameworks(pj)
        # High confidence framework should appear before low
        assert result.index("High cond") < result.index("Low cond")

    def test_tie_broken_by_revision_desc(self):
        fw_a = _make_framework("fw:a", condition="Cond A", confidence=0.6, revision=5)
        fw_b = _make_framework("fw:b", condition="Cond B", confidence=0.6, revision=1)
        pj = _make_principles_json_with_frameworks([fw_b, fw_a])
        result = _render_decision_frameworks(pj)
        # fw_a has higher revision, should appear first
        assert result.index("Cond A") < result.index("Cond B")

    def test_capped_at_max_items(self):
        frameworks = [_make_framework(f"fw:{i}", condition=f"Cond {i}", confidence=0.6) for i in range(20)]
        pj = _make_principles_json_with_frameworks(frameworks)
        result = _render_decision_frameworks(pj, max_items=5)
        # Should render at most 5 items
        assert result.count("**When**:") <= 5

    def test_renders_condition_and_consequence(self):
        fw = _make_framework(
            condition="Untested code path",
            action="Request tests",
            confidence=0.7,
        )
        pj = _make_principles_json_with_frameworks([fw])
        result = _render_decision_frameworks(pj)
        assert "Untested code path" in result
        assert "Request tests" in result


# ---------------------------------------------------------------------------
# build_system_prompt with principles_json
# ---------------------------------------------------------------------------


class TestBuildSystemPromptDecisionFrameworks:
    def test_no_decision_frameworks_section_when_principles_json_none(self):
        result = build_system_prompt("testuser", "spirit", principles_json=None)
        assert "DECISION FRAMEWORKS" not in result

    def test_decision_frameworks_section_present_with_frameworks(self):
        fw = _make_framework(confidence=0.8)
        pj = _make_principles_json_with_frameworks([fw])
        result = build_system_prompt("testuser", "spirit", principles_json=pj)
        assert "# DECISION FRAMEWORKS" in result

    def test_framework_rendering_used_not_flat_when_decision_frameworks_present(self):
        """When decision_frameworks is present, the flat legacy list must NOT appear too."""
        fw = _make_framework(confidence=0.8, condition="Modern trigger")
        pj = _make_principles_json_with_frameworks([fw])
        result = build_system_prompt("testuser", "spirit", principles_json=pj)
        # Modern trigger should be there
        assert "Modern trigger" in result
        # Legacy flat trigger from fixture should NOT be double-rendered
        assert result.count("legacy trigger") == 0

    def test_fallback_to_flat_when_decision_frameworks_absent(self):
        pj = _make_principles_json_flat_only()
        result = build_system_prompt("testuser", "spirit", principles_json=pj)
        assert "flat trigger A" in result

    def test_fallback_to_flat_when_decision_frameworks_empty_list(self):
        pj = {
            "principles": [{"trigger": "flat only", "action": "do it", "value": "v", "intensity": 0.5}],
            "decision_frameworks": {"frameworks": []},
        }
        result = build_system_prompt("testuser", "spirit", principles_json=pj)
        assert "flat only" in result

    def test_high_confidence_badge_in_system_prompt(self):
        fw = _make_framework(confidence=0.85, revision=2)
        pj = _make_principles_json_with_frameworks([fw])
        result = build_system_prompt("testuser", "spirit", principles_json=pj)
        assert "[HIGH CONFIDENCE ✓]" in result
        assert "[validated 2 times]" in result

    def test_existing_sections_unaffected(self):
        """Adding principles_json must not break existing sections."""
        fw = _make_framework(confidence=0.8)
        pj = _make_principles_json_with_frameworks([fw])
        result = build_system_prompt(
            "testuser", "spirit content", memory_content="memory", principles_json=pj
        )
        assert "IDENTITY DIRECTIVE" in result
        assert "PERSONALITY & STYLE" in result
        assert "KNOWLEDGE" in result
        assert "HOW TO RESPOND" in result
        assert "ANTI-VALUES" in result
        assert "BEHAVIORAL GUIDELINES" in result

    def test_no_decision_frameworks_section_for_empty_principles(self):
        result = build_system_prompt("testuser", "spirit", principles_json={})
        assert "DECISION FRAMEWORKS" not in result

    def test_no_decision_frameworks_section_when_all_low_conf_filtered(self):
        """All frameworks have confidence < 0.3 and ≥3 high-conf threshold not met,
        but since there ARE frameworks, low-conf ones get shown with annotation."""
        # 3 low-confidence frameworks — they should show as informational
        frameworks = [_make_framework(f"fw:{i}", condition=f"Low {i}", confidence=0.1) for i in range(3)]
        # Add 3 high-confidence to suppress low-conf
        frameworks += [_make_framework(f"fw:h{i}", condition=f"High {i}", confidence=0.8) for i in range(3)]
        pj = _make_principles_json_with_frameworks(frameworks)
        result = build_system_prompt("testuser", "spirit", principles_json=pj)
        # High-confidence ones should be present
        assert "High 0" in result
        # Low ones should be filtered since there are 3 high-conf
        assert "Low 0" not in result

    def test_username_appears_in_decision_frameworks_intro(self):
        fw = _make_framework(confidence=0.8)
        pj = _make_principles_json_with_frameworks([fw])
        result = build_system_prompt("alice", "spirit", principles_json=pj)
        # Username should appear in the intro text of the DECISION FRAMEWORKS section
        assert "alice" in result
