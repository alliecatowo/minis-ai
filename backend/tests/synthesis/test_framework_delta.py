"""Unit tests for apply_review_outcome_deltas (framework-confidence-delta-loop)."""

from __future__ import annotations

from app.synthesis.decision_frameworks import (
    apply_review_outcome_deltas,
    _tokenize,
    _tokens_overlap,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fw_dict(
    framework_id: str,
    condition: str,
    confidence: float,
    evidence_ids: list[str] | None = None,
) -> dict:
    return {
        "framework_id": framework_id,
        "condition": condition,
        "priority": "medium",
        "tradeoff": "t",
        "escalation_threshold": "e",
        "confidence": confidence,
        "specificity_level": "case_pattern",
        "evidence_ids": evidence_ids or [],
        "version": "framework-model-v1",
        "revision": 0,
        "confidence_history": [],
    }


def _principles_json(frameworks: list[dict]) -> dict:
    return {
        "decision_frameworks": {
            "version": "decision_frameworks_v1",
            "frameworks": frameworks,
            "source": "principles_motivations_normalizer",
        }
    }


def _outcome(issue_key: str, outcome: str, predicted_summary: str = "") -> dict:
    return {
        "issue_key": issue_key,
        "outcome": outcome,
        "predicted_summary": predicted_summary,
    }


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------

def test_tokenize_strips_stopwords():
    tokens = _tokenize("block the missing tests on a PR")
    assert "the" not in tokens
    assert "a" not in tokens
    assert "block" in tokens
    assert "missing" in tokens
    assert "tests" in tokens


def test_tokens_overlap_true():
    assert _tokens_overlap({"tests", "coverage"}, {"missing", "tests"}) is True


def test_tokens_overlap_false():
    assert _tokens_overlap({"auth", "token"}, {"migration", "schema"}) is False


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def test_matches_framework_by_condition_token_overlap():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests before merge", confidence=0.7, evidence_ids=["e"] * 5),
        _fw_dict("fw:auth", "authentication token expiry", confidence=0.6, evidence_ids=["e"] * 5),
    ])
    updated, updates = apply_review_outcome_deltas(
        pj, "cycle-1", [_outcome("missing-tests", "confirmed", "Add tests before merge")]
    )

    ids = {u.framework_id for u in updates}
    assert "fw:tests" in ids
    assert "fw:auth" not in ids


def test_no_match_leaves_frameworks_unchanged():
    pj = _principles_json([
        _fw_dict("fw:auth", "authentication token expiry", confidence=0.6, evidence_ids=["e"] * 5),
    ])
    updated, updates = apply_review_outcome_deltas(
        pj, "cycle-1", [_outcome("missing-tests", "confirmed", "Add tests before merge")]
    )

    assert updates == []
    # confidence unchanged
    fw = updated["decision_frameworks"]["frameworks"][0]
    assert fw["confidence"] == 0.6


# ---------------------------------------------------------------------------
# Delta math
# ---------------------------------------------------------------------------

def test_confirmed_increases_confidence():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests before merge", confidence=0.70, evidence_ids=["e"] * 5),
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "confirmed")]
    )
    assert len(updates) == 1
    u = updates[0]
    assert u.new_confidence == round(0.70 + 0.05, 4)
    assert u.net_delta > 0


def test_missed_decreases_confidence():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests before merge", confidence=0.70, evidence_ids=["e"] * 5),
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "missed")]
    )
    u = updates[0]
    assert u.new_confidence == round(0.70 - 0.08, 4)
    assert u.net_delta < 0


def test_overpredicted_decreases_confidence():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests before merge", confidence=0.60, evidence_ids=["e"] * 5),
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "overpredicted")]
    )
    u = updates[0]
    assert u.new_confidence == round(0.60 - 0.03, 4)


def test_escalated_increases_confidence():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests before merge", confidence=0.60, evidence_ids=["e"] * 5),
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "escalated")]
    )
    u = updates[0]
    assert u.new_confidence == round(0.60 + 0.02, 4)


def test_confidence_clamped_at_1():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests before merge", confidence=0.98, evidence_ids=["e"] * 5),
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "confirmed")]
    )
    assert updates[0].new_confidence <= 1.0


def test_confidence_clamped_at_0():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests before merge", confidence=0.02, evidence_ids=["e"] * 5),
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "missed")]
    )
    assert updates[0].new_confidence >= 0.0


# ---------------------------------------------------------------------------
# Sparse-data guard
# ---------------------------------------------------------------------------

def test_sparse_guard_caps_missed_delta_when_few_evidence_items():
    """missed = -0.08, but framework has 2 evidence items → capped at -0.03."""
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests before merge", confidence=0.70, evidence_ids=["e", "e2"]),
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "missed")]
    )
    assert len(updates) == 1
    u = updates[0]
    assert u.sparse_guard_applied is True
    # Net shift should be -0.03 (cap), not -0.08
    assert abs(u.net_delta) <= 0.03 + 1e-9


def test_sparse_guard_does_not_apply_when_evidence_meets_threshold():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests", confidence=0.70, evidence_ids=["e"] * 5),
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "missed")]
    )
    u = updates[0]
    assert u.sparse_guard_applied is False
    assert abs(u.net_delta) > 0.03


def test_sparse_guard_does_not_apply_when_delta_already_small():
    """escalated = +0.02 is <= cap (0.03), so guard should not trigger."""
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests", confidence=0.60, evidence_ids=["e"]),  # 1 < threshold
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "escalated")]
    )
    u = updates[0]
    assert u.sparse_guard_applied is False  # |0.02| <= 0.03 cap, guard not needed


# ---------------------------------------------------------------------------
# Version bump threshold
# ---------------------------------------------------------------------------

def test_revision_bumped_when_net_shift_exceeds_threshold():
    """confirmed = +0.05 > 0.02 → revision should increment."""
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests", confidence=0.70, evidence_ids=["e"] * 5),
    ])
    updated, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "confirmed")]
    )
    fw = updated["decision_frameworks"]["frameworks"][0]
    assert fw["revision"] == 1
    assert updates[0].revision_bumped is True


def test_revision_not_bumped_when_net_shift_at_or_below_threshold():
    """escalated = +0.02 is exactly at threshold — should NOT bump (> not >=)."""
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests", confidence=0.60, evidence_ids=["e"] * 5),
    ])
    updated, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "escalated")]
    )
    fw = updated["decision_frameworks"]["frameworks"][0]
    assert fw["revision"] == 0
    assert updates[0].revision_bumped is False


def test_revision_not_bumped_for_sparse_capped_small_delta():
    """sparse guard caps missed → -0.03 which is > 0.02, so it SHOULD bump."""
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests", confidence=0.70, evidence_ids=["e", "e2"]),
    ])
    updated, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "missed")]
    )
    fw = updated["decision_frameworks"]["frameworks"][0]
    # |net_delta| = 0.03 which is > 0.02, so revision bumps
    assert fw["revision"] == 1
    assert updates[0].revision_bumped is True


# ---------------------------------------------------------------------------
# Confidence history (audit trail)
# ---------------------------------------------------------------------------

def test_confidence_history_appended():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests", confidence=0.70, evidence_ids=["e"] * 5),
    ])
    updated, _ = apply_review_outcome_deltas(
        pj, "cycle-xyz", [_outcome("missing-tests", "confirmed")]
    )
    fw = updated["decision_frameworks"]["frameworks"][0]
    assert len(fw["confidence_history"]) == 1
    h = fw["confidence_history"][0]
    assert h["cycle_id"] == "cycle-xyz"
    assert h["outcome_type"] == "confirmed"
    assert h["prior_confidence"] == 0.70
    assert h["new_confidence"] == round(0.70 + 0.05, 4)


def test_multiple_outcomes_accumulate_history():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests before merge", confidence=0.70, evidence_ids=["e"] * 5),
    ])
    outcomes = [
        _outcome("missing-tests", "confirmed"),
        _outcome("missing-tests", "confirmed"),
    ]
    updated, updates = apply_review_outcome_deltas(pj, "c1", outcomes)
    fw = updated["decision_frameworks"]["frameworks"][0]
    assert len(fw["confidence_history"]) == 2
    assert len(updates) == 2


# ---------------------------------------------------------------------------
# Ignored outcome types
# ---------------------------------------------------------------------------

def test_new_issue_outcome_is_ignored():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests", confidence=0.70, evidence_ids=["e"] * 5),
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "new_issue")]
    )
    assert updates == []


def test_downgraded_outcome_is_ignored():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests", confidence=0.70, evidence_ids=["e"] * 5),
    ])
    _, updates = apply_review_outcome_deltas(
        pj, "c1", [_outcome("missing-tests", "downgraded")]
    )
    assert updates == []


# ---------------------------------------------------------------------------
# No frameworks / empty payload edge cases
# ---------------------------------------------------------------------------

def test_empty_principles_json_returns_empty():
    _, updates = apply_review_outcome_deltas(
        {}, "c1", [_outcome("missing-tests", "confirmed")]
    )
    assert updates == []


def test_no_frameworks_key_returns_empty():
    _, updates = apply_review_outcome_deltas(
        {"decision_frameworks": {"version": "decision_frameworks_v1"}},
        "c1",
        [_outcome("missing-tests", "confirmed")],
    )
    assert updates == []


def test_empty_issue_outcomes_returns_empty():
    pj = _principles_json([
        _fw_dict("fw:tests", "missing tests", confidence=0.70, evidence_ids=["e"] * 5),
    ])
    _, updates = apply_review_outcome_deltas(pj, "c1", [])
    assert updates == []
