from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.review_prediction import build_review_prediction_v1
from app.models.schemas import ReviewPredictionRequestV1


def _mini(**overrides) -> SimpleNamespace:
    data = {
        "username": "alliecatowo",
        "behavioral_context_json": {
            "summary": "Most direct in code review.",
            "contexts": [
                {
                    "context": "code_review",
                    "summary": "Pushes for precision, tests, and explicit boundaries.",
                    "behaviors": [
                        "flags missing coverage",
                        "asks for narrower interfaces",
                        "prefers concrete rollout plans",
                    ],
                    "communication_style": "direct but specific",
                    "decision_style": "looks for breakage before style",
                    "motivators": ["clarity", "quality"],
                    "stressors": ["hand-wavy changes"],
                    "evidence": ["Consistently asks for tests in review threads."],
                }
            ],
        },
        "motivations_json": {
            "motivations": [
                {
                    "value": "craftsmanship",
                    "category": "terminal_value",
                    "evidence_ids": ["ev-1"],
                    "confidence": 0.87,
                }
            ],
            "motivation_chains": [],
            "summary": "Values craftsmanship and clear system boundaries.",
        },
        "values_json": {
            "engineering_values": [
                {"name": "Code Quality", "description": "", "intensity": 8.8},
                {"name": "Directness", "description": "", "intensity": 8.1},
                {"name": "Pragmatism", "description": "", "intensity": 4.2},
            ]
        },
        "memory_content": (
            "In reviews they push hard on tests, rollout safety, and explicit ownership seams.\n"
            "They prefer concrete migration plans over hand-wavy compatibility claims."
        ),
        "evidence_cache": (
            "review: please add tests before merge\n"
            "review: what is the rollback plan if this migration misbehaves?\n"
            "review: auth boundary feels too implicit here"
        ),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_review_prediction_request_requires_some_change_input():
    with pytest.raises(ValidationError):
        ReviewPredictionRequestV1()


def test_build_review_prediction_returns_structured_request_changes():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        repo_name="acme/api",
        title="Refactor auth token handling for async worker",
        description="Touches JWT parsing, queue retries, and database persistence.",
        diff_summary="Updates permission checks and schema writes with no validation notes.",
        changed_files=["backend/app/auth.py", "backend/app/workers/token_queue.py"],
        author_model="senior_peer",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.version == "review_prediction_v1"
    assert prediction.repo_name == "acme/api"
    assert prediction.delivery_policy.strictness == "high"
    assert prediction.delivery_policy.teaching_mode is False
    assert prediction.expressed_feedback.approval_state == "request_changes"
    blocker_keys = {item.key for item in prediction.private_assessment.blocking_issues}
    assert "auth-boundary" in blocker_keys
    assert "runtime-behavior" in blocker_keys
    assert "test-coverage" in blocker_keys
    assert prediction.private_assessment.confidence >= 0.5
    assert prediction.expressed_feedback.comments


def test_hotfix_policy_shields_noise_for_trusted_peer():
    mini = _mini(
        values_json={
            "engineering_values": [
                {"name": "Code Quality", "description": "", "intensity": 7.4},
                {"name": "Directness", "description": "", "intensity": 6.5},
                {"name": "Pragmatism", "description": "", "intensity": 8.4},
            ]
        }
    )
    body = ReviewPredictionRequestV1(
        title="Hotfix cache timeout handling",
        description="Adjusts queue retry timing and logging for incident recovery.",
        changed_files=["backend/app/cache.py"],
        author_model="trusted_peer",
        delivery_context="incident",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.delivery_policy.shield_author_from_noise is True
    assert prediction.delivery_policy.strictness == "low"
    assert prediction.expressed_feedback.approval_state == "request_changes"
    comment_types = [comment.type for comment in prediction.expressed_feedback.comments]
    assert "note" not in comment_types


def test_positive_only_change_can_resolve_to_approve():
    mini = _mini()
    body = ReviewPredictionRequestV1(
        title="Add tests and docs for migration safety",
        description="Adds pytest coverage, rollback notes, and README docs for the migration path.",
        changed_files=["backend/tests/test_migration_flow.py", "backend/README.md"],
        author_model="unknown",
        delivery_context="normal",
    )

    prediction = build_review_prediction_v1(mini, body)

    assert prediction.private_assessment.blocking_issues == []
    assert prediction.private_assessment.positive_signals
    assert prediction.expressed_feedback.approval_state == "approve"
