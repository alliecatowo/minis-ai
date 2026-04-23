from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.webhooks import (
    handle_issue_comment,
    handle_pull_request_opened,
    handle_pull_request_review,
)


@pytest.mark.asyncio
async def test_handle_pull_request_opened_records_prediction_after_posting_review():
    payload = {
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "author_association": "MEMBER",
            "user": {"login": "octo-dev"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    prediction = {
        "version": "review_prediction_v1",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.8,
        },
        "delivery_policy": {
            "author_model": "trusted_peer",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": True,
            "shield_author_from_noise": True,
            "rationale": "keep it focused",
        },
        "expressed_feedback": {
            "summary": "Looks good. One small concern.",
            "approval_state": "comment",
            "comments": [],
        },
    }

    with patch("app.webhooks.get_pr_requested_reviewers", AsyncMock(return_value=["allie"])) as reviewers:
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch(
                    "app.webhooks.get_mini",
                    AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                ):
                    with patch(
                        "app.webhooks.get_review_prediction",
                        AsyncMock(return_value=prediction),
                    ) as get_prediction:
                        with patch(
                            "app.webhooks.render_review_prediction",
                            return_value="Looks good. One small concern.",
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
    get_prediction.assert_awaited_once_with(
        "mini-1",
        repo_name="octo-org/hello-world",
        pr_title="Refactor retry client",
        pr_body="This extracts retry policy handling.",
        diff="diff --git a/x b/x",
        changed_files=["app/retry.py"],
        author_model="senior_peer",
        delivery_context="normal",
    )
    post_review.assert_awaited_once()
    record_prediction.assert_awaited_once()

    kwargs = record_prediction.await_args.kwargs
    assert kwargs["mini_id"] == "mini-1"
    assert kwargs["installation_id"] == 321
    assert kwargs["owner"] == "octo-org"
    assert kwargs["repo"] == "hello-world"
    assert kwargs["pr_number"] == 7
    assert kwargs["pr_title"] == "Refactor retry client"
    assert kwargs["pr_html_url"] == "https://github.com/octo-org/hello-world/pull/7"
    assert kwargs["reviewer_login"] == "allie"
    assert kwargs["prediction"] == prediction
    assert kwargs["github_review_id"] == 55
    assert kwargs["github_review_state"] == "COMMENTED"
    assert kwargs["author_login"] == "octo-dev"
    assert kwargs["author_association"] == "MEMBER"


@pytest.mark.asyncio
async def test_handle_pull_request_opened_infers_author_model_from_github_context():
    payload = {
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "author_association": "FIRST_TIME_CONTRIBUTOR",
            "user": {"login": "new-contributor"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    with patch("app.webhooks.get_pr_requested_reviewers", AsyncMock(return_value=["allie"])):
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch(
                    "app.webhooks.get_mini",
                    AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                ):
                    with patch(
                        "app.webhooks.get_review_prediction",
                        AsyncMock(
                            return_value={
                                "version": "review_prediction_v1",
                                "private_assessment": {
                                    "blocking_issues": [],
                                    "non_blocking_issues": [],
                                    "open_questions": [],
                                    "positive_signals": [],
                                    "confidence": 0.8,
                                },
                                "delivery_policy": {
                                    "author_model": "junior_peer",
                                    "context": "normal",
                                    "strictness": "medium",
                                    "teaching_mode": True,
                                    "shield_author_from_noise": False,
                                    "rationale": "mapped from author association",
                                },
                                "expressed_feedback": {
                                    "summary": "Looks good. One small concern.",
                                    "approval_state": "comment",
                                    "comments": [],
                                },
                            }
                        ),
                    ) as get_prediction:
                        with patch(
                            "app.webhooks.render_review_prediction",
                            return_value="Looks good. One small concern.",
                        ):
                            with patch(
                                "app.webhooks.post_pr_review",
                                AsyncMock(return_value={"id": 55, "state": "COMMENTED"}),
                            ):
                                with patch(
                                    "app.webhooks.record_review_prediction",
                                    AsyncMock(return_value=True),
                                ):
                                    await handle_pull_request_opened(payload)

    assert get_prediction.await_args.kwargs["author_model"] == "junior_peer"


@pytest.mark.asyncio
async def test_handle_issue_comment_passes_inferred_author_model_to_mention_response():
    payload = {
        "comment": {"body": "@allie-mini can you take a look?"},
        "issue": {"number": 12, "pull_request": {"url": "https://api.github.com/repos/x/y/pulls/12"}},
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    with patch(
        "app.webhooks.get_pr_details",
        AsyncMock(
            return_value={
                "title": "Refactor retry client",
                "body": "This extracts retry policy handling.",
                "author_association": "COLLABORATOR",
                "user": {"login": "trusted-contributor"},
            }
        ),
    ):
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch(
                    "app.webhooks.get_mini",
                    AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                ):
                    with patch(
                        "app.webhooks.generate_mention_response",
                        AsyncMock(return_value="Looks good. One small concern."),
                    ) as generate_response:
                        with patch("app.webhooks.post_issue_comment", AsyncMock()):
                            await handle_issue_comment(payload)

    assert generate_response.await_args.kwargs["author_model"] == "trusted_peer"


@pytest.mark.asyncio
async def test_handle_pull_request_review_records_human_review_outcome():
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
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-123", "username": "human-reviewer"}),
    ):
        with patch(
            "app.webhooks.record_human_review_outcome",
            AsyncMock(return_value=True),
        ) as record_human_review_outcome:
            await handle_pull_request_review(payload)

    record_human_review_outcome.assert_awaited_once()
    kwargs = record_human_review_outcome.await_args.kwargs
    assert kwargs["mini_id"] == "mini-123"
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
    }

    with patch(
        "app.webhooks.record_human_review_outcome",
        AsyncMock(return_value=True),
    ) as record_human_review_outcome:
        await handle_pull_request_review(payload)

    record_human_review_outcome.assert_not_awaited()
