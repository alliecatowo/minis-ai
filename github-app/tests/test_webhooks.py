from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.webhooks import handle_pull_request_opened, handle_pull_request_review


@pytest.mark.asyncio
async def test_handle_pull_request_opened_records_prediction_after_posting_review():
    payload = {
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "user": {"login": "author-user"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    with patch("app.webhooks.get_pr_requested_reviewers", AsyncMock(return_value=["allie"])) as reviewers:
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_mini",
                AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
            ):
                with patch(
                    "app.webhooks.generate_review",
                    AsyncMock(return_value="Looks good. One small concern."),
                ):
                    with patch(
                        "app.webhooks.post_pr_review",
                        AsyncMock(return_value={"id": 55, "state": "COMMENTED"}),
                    ) as post_review:
                        with patch(
                            "app.webhooks.record_review_prediction",
                            AsyncMock(return_value=True),
                        ) as record_prediction:
                            await handle_pull_request_opened(payload)

    reviewers.assert_awaited_once_with(321, "octo-org", "hello-world", 7)
    post_review.assert_awaited_once()
    record_prediction.assert_awaited_once()

    kwargs = record_prediction.await_args.kwargs
    assert kwargs["installation_id"] == 321
    assert kwargs["owner"] == "octo-org"
    assert kwargs["repo"] == "hello-world"
    assert kwargs["pr_number"] == 7
    assert kwargs["pr_title"] == "Refactor retry client"
    assert kwargs["pr_author_login"] == "author-user"
    assert kwargs["reviewer_login"] == "allie"
    assert kwargs["mini"] == {"id": "mini-1", "username": "allie"}
    assert kwargs["github_review_id"] == 55
    assert kwargs["github_review_state"] == "COMMENTED"
    assert "Review by @allie" in kwargs["predicted_review_body"]


@pytest.mark.asyncio
async def test_handle_pull_request_review_records_human_review_event():
    payload = {
        "action": "submitted",
        "review": {
            "id": 888,
            "state": "APPROVED",
            "body": "Looks good to me.",
            "user": {"login": "human-reviewer", "type": "User"},
        },
        "pull_request": {
            "number": 9,
            "title": "Fix backoff jitter",
            "html_url": "https://github.com/octo-org/hello-world/pull/9",
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 123},
    }

    with patch(
        "app.webhooks.record_human_review_event",
        AsyncMock(return_value=True),
    ) as record_human_review_event:
        await handle_pull_request_review(payload)

    record_human_review_event.assert_awaited_once()
    kwargs = record_human_review_event.await_args.kwargs
    assert kwargs["installation_id"] == 123
    assert kwargs["owner"] == "octo-org"
    assert kwargs["repo"] == "hello-world"
    assert kwargs["pr_number"] == 9
    assert kwargs["reviewer_login"] == "human-reviewer"
    assert kwargs["action"] == "submitted"
    assert kwargs["review"]["id"] == 888


@pytest.mark.asyncio
async def test_handle_pull_request_review_ignores_non_human_reviews():
    payload = {
        "action": "submitted",
        "review": {
            "id": 888,
            "state": "COMMENTED",
            "body": "",
            "user": {"login": "minis-pr-reviewer[bot]", "type": "Bot"},
        },
        "pull_request": {
            "number": 9,
            "title": "Fix backoff jitter",
            "html_url": "https://github.com/octo-org/hello-world/pull/9",
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 123},
    }

    with patch(
        "app.webhooks.record_human_review_event",
        AsyncMock(return_value=True),
    ) as record_human_review_event:
        await handle_pull_request_review(payload)

    record_human_review_event.assert_not_awaited()
