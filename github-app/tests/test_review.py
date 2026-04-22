from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.review import (
    generate_mention_response,
    generate_review,
    get_mini,
    infer_author_model_from_github_context,
)


class _AsyncClientStub:
    def __init__(
        self,
        *,
        get_responses: list[httpx.Response] | None = None,
        post_responses: list[httpx.Response] | None = None,
    ):
        self._get_responses = list(get_responses or [])
        self._post_responses = list(post_responses or [])
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float,
    ):
        self.calls.append(
            {"method": "GET", "url": url, "headers": headers, "timeout": timeout}
        )
        return self._get_responses.pop(0)

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict,
        timeout: float,
    ):
        self.calls.append(
            {
                "method": "POST",
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self._post_responses.pop(0)


def _response(method: str, url: str, *, status_code: int = 200, json: dict | None = None):
    return httpx.Response(
        status_code,
        request=httpx.Request(method, url),
        json=json,
    )


@pytest.mark.asyncio
async def test_get_mini_uses_trusted_lookup_path_and_header():
    stub = _AsyncClientStub(
        get_responses=[
            _response(
                "GET",
                f"{settings.minis_api_url}/api/minis/trusted/by-username/alliecatowo",
                json={
                    "id": "mini-123",
                    "username": "alliecatowo",
                    "display_name": "Allie",
                    "avatar_url": None,
                    "status": "ready",
                    "system_prompt": "be pragmatic",
                },
            )
        ]
    )

    with patch.object(settings, "trusted_service_secret", "secret-for-tests", create=True):
        with patch("app.review.httpx.AsyncClient", return_value=stub):
            mini = await get_mini("alliecatowo")

    assert mini is not None
    assert mini["system_prompt"] == "be pragmatic"
    assert stub.calls == [
        {
            "method": "GET",
            "url": f"{settings.minis_api_url}/api/minis/trusted/by-username/alliecatowo",
            "headers": {"X-Trusted-Service-Secret": "secret-for-tests"},
            "timeout": 10.0,
        }
    ]


@pytest.mark.asyncio
async def test_generate_review_calls_trusted_review_prediction_endpoint_and_formats_response():
    prediction = {
        "version": "review_prediction_v1",
        "reviewer_username": "alliecatowo",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.7,
        },
        "delivery_policy": {
            "author_model": "unknown",
            "context": "hotfix",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": False,
            "rationale": "fallback defaults",
        },
        "expressed_feedback": {
            "summary": "Would likely request changes and surface the highest-severity concerns first.",
            "approval_state": "request_changes",
            "comments": [
                {
                    "type": "blocker",
                    "disposition": "request_changes",
                    "issue_key": "auth-boundary",
                    "summary": "Likely to scrutinize auth and permission boundaries before approving.",
                    "rationale": "Credentials changes are high-severity review territory.",
                }
            ],
        },
    }
    stub = _AsyncClientStub(
        post_responses=[
            _response(
                "POST",
                "https://backend.test/api/minis/trusted/mini-123/review-prediction",
                json=prediction,
            )
        ]
    )

    with patch.object(settings, "minis_api_url", "https://backend.test"):
        with patch.object(settings, "trusted_service_secret", "secret-for-tests", create=True):
            with patch("app.review.httpx.AsyncClient", return_value=stub):
                review_text = await generate_review(
                    mini={"id": "mini-123"},
                    repo_name="octo/repo",
                    pr_title="Hotfix auth boundary",
                    pr_body="Tightens token checks around webhook auth.",
                    diff="diff --git a/app/auth.py b/app/auth.py",
                    changed_files=["app/auth.py"],
                    delivery_context="hotfix",
                )

    assert "Predicted stance" in review_text
    assert "`request changes`" in review_text
    assert "auth-boundary" in review_text
    assert "Credentials changes are high-severity review territory." in review_text
    assert stub.calls == [
        {
            "method": "POST",
            "url": "https://backend.test/api/minis/trusted/mini-123/review-prediction",
            "headers": {"X-Trusted-Service-Secret": "secret-for-tests"},
            "json": {
                "repo_name": "octo/repo",
                "title": "Hotfix auth boundary",
                "description": "Tightens token checks around webhook auth.",
                "diff_summary": "diff --git a/app/auth.py b/app/auth.py",
                "changed_files": ["app/auth.py"],
                "author_model": "unknown",
                "delivery_context": "hotfix",
            },
            "timeout": 30.0,
        }
    ]


@pytest.mark.asyncio
async def test_generate_mention_response_labels_structured_prediction_for_non_review_prompt():
    prediction = {
        "version": "review_prediction_v1",
        "reviewer_username": "alliecatowo",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.7,
        },
        "delivery_policy": {
            "author_model": "unknown",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": False,
            "rationale": "fallback defaults",
        },
        "expressed_feedback": {
            "summary": "Would likely leave a small set of comments without blocking the change.",
            "approval_state": "comment",
            "comments": [],
        },
    }
    stub = _AsyncClientStub(
        post_responses=[
            _response(
                "POST",
                "https://backend.test/api/minis/trusted/mini-123/review-prediction",
                json=prediction,
            )
        ]
    )

    with patch.object(settings, "minis_api_url", "https://backend.test"):
        with patch.object(settings, "trusted_service_secret", "secret-for-tests", create=True):
            with patch("app.review.httpx.AsyncClient", return_value=stub):
                review_text = await generate_mention_response(
                    mini={"id": "mini-123"},
                    user_message="@alliecatowo-mini what do you think about the auth layer?",
                    repo_name="octo/repo",
                    pr_title="Update auth flow",
                    pr_body="",
                    diff="diff --git a/app/auth.py b/app/auth.py",
                )

    assert "structured review prediction" in review_text.lower()
    assert "`comment`" in review_text


@pytest.mark.asyncio
async def test_get_mini_requires_trusted_service_secret_config():
    with patch.object(settings, "trusted_service_secret", "", create=True):
        mini = await get_mini("alliecatowo")

    assert mini is None


def test_infer_author_model_from_github_context_uses_author_association_mapping():
    assert infer_author_model_from_github_context(author_association="OWNER") == "senior_peer"
    assert (
        infer_author_model_from_github_context(author_association="collaborator")
        == "trusted_peer"
    )
    assert (
        infer_author_model_from_github_context(author_association="FIRST_TIME_CONTRIBUTOR")
        == "junior_peer"
    )
    assert infer_author_model_from_github_context(author_association="MANNEQUIN") == "unknown"


def test_infer_author_model_from_github_context_falls_back_to_repo_owner_match():
    assert (
        infer_author_model_from_github_context(
            author_association=None,
            author_login="octo-org",
            repo_owner_login="octo-org",
        )
        == "senior_peer"
    )
