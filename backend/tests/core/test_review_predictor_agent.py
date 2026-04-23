import json
from unittest.mock import AsyncMock, patch

import pytest
from app.core.review_predictor_agent import predict_review
from app.models.schemas import ReviewPredictionRequestV1, ReviewPredictionV1

@pytest.mark.asyncio
async def test_predict_review_agent_success():
    mini = AsyncMock()
    mini.username = "testuser"
    mini.system_prompt = "You are a test user."
    mini.memory_content = "Memory content"
    mini.evidence_cache = "Evidence cache"
    mini.principles_json = {"principles": []}

    body = ReviewPredictionRequestV1(
        repo_name="test/repo",
        title="Test PR",
        description="This is a test PR",
        changed_files=["file1.py"],
        author_model="junior_peer",
        delivery_context="normal"
    )
    
    session = AsyncMock()
    
    mock_prediction = {
        "version": "review_prediction_v1",
        "reviewer_username": "testuser",
        "repo_name": "test/repo",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.9
        },
        "delivery_policy": {
            "author_model": "junior_peer",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": True,
            "shield_author_from_noise": False,
            "rationale": "Test rationale"
        },
        "expressed_feedback": {
            "summary": "Looks good",
            "comments": [],
            "approval_state": "approve"
        }
    }
    
    with patch("app.core.review_predictor_agent.run_agent") as mock_run_agent:
        mock_run_agent.return_value = AsyncMock(
            final_response=json.dumps(mock_prediction)
        )
        
        result = await predict_review(mini, body, session)
        
        assert isinstance(result, ReviewPredictionV1)
        assert result.reviewer_username == "testuser"
        assert result.expressed_feedback.approval_state == "approve"
        assert mock_run_agent.called

@pytest.mark.asyncio
async def test_predict_review_agent_fallback_on_failure():
    mini = AsyncMock()
    mini.username = "testuser"
    mini.system_prompt = "You are a test user."
    mini.behavioral_context_json = None
    mini.motivations_json = None
    mini.values_json = None
    mini.memory_content = None
    mini.evidence_cache = None
    mini.principles_json = None

    body = ReviewPredictionRequestV1(
        title="Test PR",
    )
    
    session = AsyncMock()
    
    with patch("app.core.review_predictor_agent.run_agent") as mock_run_agent:
        mock_run_agent.return_value = AsyncMock(final_response=None)
        
        # This should fall back to heuristic-based build_review_prediction_v1
        result = await predict_review(mini, body, session)
        
        assert isinstance(result, ReviewPredictionV1)
        assert result.reviewer_username == "testuser"
        assert mock_run_agent.called
