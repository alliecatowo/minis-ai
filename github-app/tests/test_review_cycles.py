from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.review_cycles import (
    record_human_review_event,
    record_review_prediction,
)


class _AsyncClientStub:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict | None = None,
        timeout: float,
    ):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return self._response


@pytest.mark.asyncio
async def test_record_review_prediction_uses_trusted_endpoint_and_payload_shape():
    stub = _AsyncClientStub(
        httpx.Response(
            200,
            request=httpx.Request(
                "POST",
                f"{settings.minis_api_url}/api/review-cycles/trusted/github/predictions",
            ),
            json={"ok": True},
        )
    )

    with patch.object(settings, "trusted_service_secret", "secret-for-tests"):
        with patch("app.review_cycles.httpx.AsyncClient", return_value=stub):
            result = await record_review_prediction(
                installation_id=99,
                owner="octo-org",
                repo="hello-world",
                pr_number=42,
                pr_title="Tighten retry behavior",
                pr_author_login="author-user",
                pr_html_url="https://github.com/octo-org/hello-world/pull/42",
                reviewer_login="alliecatowo",
                mini={"id": "mini-123", "username": "alliecatowo"},
                predicted_review_body="### Review by @alliecatowo's mini",
                github_review_id=12345,
                github_review_state="COMMENTED",
            )

    assert result is True
    assert len(stub.calls) == 1

    call = stub.calls[0]
    assert call["url"] == (
        f"{settings.minis_api_url}/api/review-cycles/trusted/github/predictions"
    )
    assert call["headers"] == {"X-Trusted-Service-Secret": "secret-for-tests"}
    assert call["timeout"] == 10.0
    assert call["json"]["installation_id"] == 99
    assert call["json"]["repository"] == {"owner": "octo-org", "name": "hello-world"}
    assert call["json"]["pull_request"]["number"] == 42
    assert call["json"]["reviewer_login"] == "alliecatowo"
    assert call["json"]["predicted_review"]["github_review_id"] == 12345
    assert call["json"]["predicted_review"]["github_state"] == "COMMENTED"
    assert call["json"]["predicted_review"]["verdict"] == "comment"
    assert call["json"]["predicted_review"]["generator"] == {
        "kind": "minis_github_app",
        "model": settings.default_llm_model,
        "mini_id": "mini-123",
        "mini_username": "alliecatowo",
    }
    assert call["json"]["predicted_review"]["submitted_at"]


@pytest.mark.asyncio
async def test_record_human_review_event_uses_trusted_endpoint_and_normalizes_verdict():
    stub = _AsyncClientStub(
        httpx.Response(
            200,
            request=httpx.Request(
                "POST",
                f"{settings.minis_api_url}/api/review-cycles/trusted/github/human-review-events",
            ),
            json={"ok": True},
        )
    )

    with patch.object(settings, "trusted_service_secret", "secret-for-tests"):
        with patch("app.review_cycles.httpx.AsyncClient", return_value=stub):
            result = await record_human_review_event(
                installation_id=99,
                owner="octo-org",
                repo="hello-world",
                pr_number=42,
                pr_title="Tighten retry behavior",
                pr_html_url="https://github.com/octo-org/hello-world/pull/42",
                reviewer_login="human-reviewer",
                action="submitted",
                review={
                    "id": 987,
                    "state": "CHANGES_REQUESTED",
                    "body": "Please separate transport retries from auth retries.",
                    "submitted_at": "2026-04-22T17:00:00Z",
                    "html_url": "https://github.com/octo-org/hello-world/pull/42#pullrequestreview-987",
                    "commit_id": "abc123",
                    "author_association": "MEMBER",
                },
            )

    assert result is True
    assert len(stub.calls) == 1

    call = stub.calls[0]
    assert call["url"] == (
        f"{settings.minis_api_url}/api/review-cycles/trusted/github/human-review-events"
    )
    assert call["headers"] == {"X-Trusted-Service-Secret": "secret-for-tests"}
    assert call["json"]["reviewer_login"] == "human-reviewer"
    assert call["json"]["human_review"]["action"] == "submitted"
    assert call["json"]["human_review"]["github_review_id"] == 987
    assert call["json"]["human_review"]["verdict"] == "request_changes"
    assert call["json"]["human_review"]["captured_at"]
