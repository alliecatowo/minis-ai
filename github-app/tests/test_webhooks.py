from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.webhooks import (
    _bot_reviews_for_reviewer,
    _last_posted_sha_cache,
    _review_already_posted,
    handle_issue_comment,
    handle_pr_review_comment,
    handle_pr_review_comment_reaction,
    handle_pr_review_thread_reply,
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

    with patch(
        "app.webhooks.get_pr_requested_reviewers",
        AsyncMock(return_value=[{"login": "allie", "type": "User", "site_admin": False}]),
    ) as reviewers:
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch(
                    "app.webhooks.get_repo_collaborator_permission",
                    AsyncMock(return_value=None),
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

    with patch(
        "app.webhooks.get_pr_requested_reviewers",
        AsyncMock(return_value=[{"login": "allie", "type": "User", "site_admin": False}]),
    ):
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch(
                    "app.webhooks.get_repo_collaborator_permission",
                    AsyncMock(return_value=None),
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
                with patch("app.webhooks.get_repo_collaborator_permission", AsyncMock(return_value=None)):
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
async def test_handle_issue_comment_review_request_posts_pr_review_and_records_prediction():
    payload = {
        "comment": {
            "body": "@allie-mini please review this PR",
            "html_url": "https://github.com/octo-org/hello-world/pull/12#issuecomment-1",
        },
        "issue": {
            "number": 12,
            "html_url": "https://github.com/octo-org/hello-world/pull/12",
            "pull_request": {"url": "https://api.github.com/repos/x/y/pulls/12"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }
    prediction = {
        "version": "review_prediction_v1",
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "reviewer_username": "allie",
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
            "teaching_mode": False,
            "shield_author_from_noise": True,
            "rationale": "explicit reviewer request",
        },
        "expressed_feedback": {
            "summary": "Would leave one focused review note.",
            "approval_state": "comment",
            "comments": [],
        },
    }

    with patch(
        "app.webhooks.get_pr_details",
        AsyncMock(
            return_value={
                "title": "Refactor retry client",
                "body": "This extracts retry policy handling.",
                "html_url": "https://github.com/octo-org/hello-world/pull/12",
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
                with patch("app.webhooks.get_repo_collaborator_permission", AsyncMock(return_value=None)):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.get_review_prediction",
                            AsyncMock(return_value=prediction),
                        ) as get_prediction:
                            with patch(
                                "app.webhooks.post_pr_review",
                                AsyncMock(return_value={"id": 77, "state": "COMMENTED"}),
                            ) as post_review:
                                with patch(
                                    "app.webhooks.record_review_prediction",
                                    AsyncMock(return_value=True),
                                ) as record_prediction:
                                    with patch(
                                        "app.webhooks.generate_mention_response",
                                        AsyncMock(),
                                    ) as generate_response:
                                        with patch(
                                            "app.webhooks.post_issue_comment",
                                            AsyncMock(),
                                        ) as post_issue_comment:
                                            await handle_issue_comment(payload)

    get_prediction.assert_awaited_once_with(
        "mini-1",
        repo_name="octo-org/hello-world",
        pr_title="Refactor retry client",
        pr_body="This extracts retry policy handling.",
        diff="diff --git a/x b/x",
        changed_files=["app/retry.py"],
        author_model="trusted_peer",
        delivery_context="normal",
    )
    post_review.assert_awaited_once()
    body = post_review.await_args.kwargs["body"]
    assert "Reviewer mode: structured prediction for the requested reviewer." in body
    assert "**Predicted stance:** `comment`" in body
    generate_response.assert_not_awaited()
    post_issue_comment.assert_not_awaited()
    record_prediction.assert_awaited_once()

    kwargs = record_prediction.await_args.kwargs
    assert kwargs["mini_id"] == "mini-1"
    assert kwargs["installation_id"] == 321
    assert kwargs["owner"] == "octo-org"
    assert kwargs["repo"] == "hello-world"
    assert kwargs["pr_number"] == 12
    assert kwargs["pr_title"] == "Refactor retry client"
    assert kwargs["pr_html_url"] == "https://github.com/octo-org/hello-world/pull/12"
    assert kwargs["reviewer_login"] == "allie"
    assert kwargs["prediction"] == prediction
    assert kwargs["github_review_id"] == 77
    assert kwargs["github_review_state"] == "COMMENTED"
    assert kwargs["author_login"] == "trusted-contributor"
    assert kwargs["author_association"] == "COLLABORATOR"


@pytest.mark.asyncio
async def test_handle_pr_review_comment_mentions_reply_in_review_thread():
    payload = {
        "comment": {"id": 987, "body": "@allie-mini does this satisfy the retry concern?"},
        "pull_request": {
            "number": 12,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "author_association": "COLLABORATOR",
            "user": {"login": "trusted-contributor"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
        with patch(
            "app.webhooks.get_pr_changed_files",
            AsyncMock(return_value=["app/retry.py"]),
        ):
            with patch(
                "app.webhooks.get_repo_collaborator_permission",
                AsyncMock(return_value=None),
            ):
                with patch(
                    "app.webhooks.get_mini",
                    AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                ):
                    with patch(
                        "app.webhooks.generate_mention_response",
                        AsyncMock(return_value="Structured reply."),
                    ) as generate_response:
                        with patch(
                            "app.webhooks.post_pr_review_comment_reply",
                            AsyncMock(return_value={"id": 654}),
                        ) as post_reply:
                            with patch("app.webhooks.post_issue_comment", AsyncMock()) as post_issue:
                                await handle_pr_review_comment(payload)

    assert generate_response.await_args.kwargs["author_model"] == "trusted_peer"
    post_reply.assert_awaited_once()
    assert post_reply.await_args.kwargs["pr_number"] == 12
    assert post_reply.await_args.kwargs["comment_id"] == 987
    assert "Structured reply." in post_reply.await_args.kwargs["body"]
    post_issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_pull_request_opened_uses_requested_reviewer_payload_on_review_requested():
    payload = {
        "action": "review_requested",
        "requested_reviewer": {"login": "allie", "type": "User"},
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

    with patch("app.webhooks.get_pr_requested_reviewers", AsyncMock()) as reviewers:
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch("app.webhooks.get_repo_collaborator_permission", AsyncMock(return_value=None)):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.get_review_prediction",
                            AsyncMock(
                                return_value={
                                    "version": "review_prediction_v1",
                                    "delivery_policy": {"author_model": "senior_peer"},
                                    "expressed_feedback": {
                                        "summary": "Looks good.",
                                        "approval_state": "comment",
                                        "comments": [],
                                    },
                                }
                            ),
                        ) as get_prediction:
                            with patch(
                                "app.webhooks.render_review_prediction",
                                return_value="Looks good.",
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

    reviewers.assert_not_awaited()
    assert get_prediction.await_args.kwargs["author_model"] == "senior_peer"


@pytest.mark.asyncio
async def test_handle_review_requested_posts_reviewer_mode_prediction_when_available():
    payload = {
        "action": "review_requested",
        "requested_reviewer": {"login": "allie", "type": "User"},
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
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "reviewer_username": "allie",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.82,
        },
        "delivery_policy": {
            "author_model": "senior_peer",
            "context": "normal",
            "strictness": "medium",
            "teaching_mode": False,
            "shield_author_from_noise": True,
            "rationale": "reviewer mode",
        },
        "expressed_feedback": {
            "summary": "Would likely leave one focused note.",
            "approval_state": "comment",
            "comments": [],
        },
        "framework_signals": [
            {"name": "Prefer focused diffs", "confidence": 0.82, "revision_count": 2}
        ],
    }

    with patch("app.webhooks.get_pr_requested_reviewers", AsyncMock()) as reviewers:
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch("app.webhooks.get_pr_changed_files", AsyncMock(return_value=["app/retry.py"])):
                with patch("app.webhooks.get_repo_collaborator_permission", AsyncMock(return_value=None)):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.get_review_prediction",
                            AsyncMock(return_value=prediction),
                        ) as get_prediction:
                            with patch(
                                "app.webhooks.post_pr_review",
                                AsyncMock(return_value={"id": 55, "state": "COMMENTED"}),
                            ) as post_review:
                                with patch(
                                    "app.webhooks.record_review_prediction",
                                    AsyncMock(return_value=True),
                                ):
                                    await handle_pull_request_opened(payload)

    reviewers.assert_not_awaited()
    get_prediction.assert_awaited_once()
    body = post_review.await_args.kwargs["body"]
    assert "Reviewer mode: structured prediction for the requested reviewer." in body
    assert "**Predicted stance:** `comment`" in body
    assert "Framework signals" in body
    assert "[confidence 82%]" in body


@pytest.mark.asyncio
async def test_handle_review_requested_posts_prediction_supplied_inline_suggestion():
    payload = {
        "action": "review_requested",
        "requested_reviewer": {"login": "allie", "type": "User"},
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "head": {"sha": "abc123"},
            "author_association": "MEMBER",
            "user": {"login": "octo-dev"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }
    prediction = {
        "version": "review_prediction_v1",
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "reviewer_username": "allie",
        "private_assessment": {
            "blocking_issues": [
                {
                    "key": "retry-coverage",
                    "summary": "Tests required.",
                    "rationale": "Retry paths regress easily.",
                    "confidence": 0.9,
                    "framework_id": "fw-retry-tests",
                    "revision": 6,
                }
            ],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.9,
        },
        "delivery_policy": {
            "author_model": "senior_peer",
            "context": "normal",
            "strictness": "high",
            "teaching_mode": False,
            "shield_author_from_noise": True,
            "rationale": "reviewer mode",
        },
        "expressed_feedback": {
            "summary": "Would request one focused test change.",
            "approval_state": "request_changes",
            "comments": [
                {
                    "type": "blocker",
                    "disposition": "request_changes",
                    "issue_key": "retry-coverage",
                    "summary": "Please cover the retry exhaustion path.",
                    "rationale": "This path decides whether failures are surfaced.",
                    "path": "app/retry.py",
                    "line": 42,
                    "side": "RIGHT",
                    "suggested_replacement": "raise RetryExhaustedError(last_error)",
                }
            ],
        },
    }

    with patch("app.webhooks.get_pr_requested_reviewers", AsyncMock()) as reviewers:
        with patch("app.webhooks.list_pr_reviews", AsyncMock(return_value=[])) as list_reviews:
            with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
                with patch(
                    "app.webhooks.get_pr_changed_files",
                    AsyncMock(return_value=["app/retry.py"]),
                ):
                    with patch(
                        "app.webhooks.get_repo_collaborator_permission",
                        AsyncMock(return_value=None),
                    ):
                        with patch(
                            "app.webhooks.get_mini",
                            AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                        ):
                            with patch(
                                "app.webhooks.get_review_prediction",
                                AsyncMock(return_value=prediction),
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

    reviewers.assert_not_awaited()
    list_reviews.assert_awaited_once_with(321, "octo-org", "hello-world", 7)
    assert "<!-- minis-review:allie:abc123 -->" in post_review.await_args.kwargs["body"]
    assert post_review.await_args.kwargs["comments"] == [
        {
            "path": "app/retry.py",
            "line": 42,
            "side": "RIGHT",
            "body": (
                "### Review by @allie's mini\n\n"
                "**Blocker `retry-coverage`**: Please cover the retry exhaustion path. "
                "Why: This path decides whether failures are surfaced. "
                "[from framework: fw-retry-tests, validated 6×]\n\n"
                "```suggestion\n"
                "raise RetryExhaustedError(last_error)\n"
                "```\n\n"
                "---\n"
                "*This review was generated by [allie's mini](https://github.com/allie) "
                "using the Minis backend review-prediction API.*"
            ),
        }
    ]
    assert record_prediction.await_args.kwargs["github_head_sha"] == "abc123"


@pytest.mark.asyncio
async def test_handle_review_requested_skips_duplicate_review_for_same_head_sha():
    payload = {
        "action": "review_requested",
        "requested_reviewer": {"login": "allie", "type": "User"},
        "pull_request": {
            "number": 7,
            "title": "Refactor retry client",
            "body": "This extracts retry policy handling.",
            "html_url": "https://github.com/octo-org/hello-world/pull/7",
            "head": {"sha": "abc123"},
            "author_association": "MEMBER",
            "user": {"login": "octo-dev"},
        },
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "installation": {"id": 321},
    }

    with patch("app.webhooks.get_pr_requested_reviewers", AsyncMock()) as reviewers:
        with patch(
            "app.webhooks.list_pr_reviews",
            AsyncMock(return_value=[{"body": "prior\n<!-- minis-review:allie:abc123 -->"}]),
        ) as list_reviews:
            with patch(
                "app.webhooks.get_mini",
                AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
            ):
                with patch("app.webhooks.get_pr_diff", AsyncMock()) as get_diff:
                    with patch("app.webhooks.get_review_prediction", AsyncMock()) as get_prediction:
                        with patch("app.webhooks.post_pr_review", AsyncMock()) as post_review:
                            await handle_pull_request_opened(payload)

    reviewers.assert_not_awaited()
    list_reviews.assert_awaited_once_with(321, "octo-org", "hello-world", 7)
    get_diff.assert_not_awaited()
    get_prediction.assert_not_awaited()
    post_review.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_review_requested_posts_restrained_unavailable_message_when_gated():
    payload = {
        "action": "review_requested",
        "requested_reviewer": {"login": "allie", "type": "User"},
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
        "prediction_available": False,
        "mode": "gated",
        "unavailable_reason": "mini is still synthesizing review frameworks",
        "reviewer_username": "allie",
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
            "confidence": 0.0,
        },
        "delivery_policy": {},
        "expressed_feedback": {
            "summary": "Review prediction unavailable.",
            "approval_state": "uncertain",
            "comments": [],
        },
    }

    with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
        with patch("app.webhooks.get_pr_changed_files", AsyncMock(return_value=["app/retry.py"])):
            with patch("app.webhooks.get_repo_collaborator_permission", AsyncMock(return_value=None)):
                with patch(
                    "app.webhooks.get_mini",
                    AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                ):
                    with patch(
                        "app.webhooks.get_review_prediction",
                        AsyncMock(return_value=prediction),
                    ):
                        with patch(
                            "app.webhooks.post_pr_review",
                            AsyncMock(return_value={"id": 55, "state": "COMMENTED"}),
                        ) as post_review:
                            with patch(
                                "app.webhooks.record_review_prediction",
                                AsyncMock(return_value=True),
                            ):
                                await handle_pull_request_opened(payload)

    body = post_review.await_args.kwargs["body"]
    assert "Review prediction unavailable" in body
    assert "Reviewer mode was requested for this PR" in body
    assert "**Mode:** `gated`" in body
    assert "Predicted stance" not in body


@pytest.mark.asyncio
async def test_handle_review_requested_skips_when_requested_reviewer_has_no_mini():
    payload = {
        "action": "review_requested",
        "requested_reviewer": {"login": "allie", "type": "User"},
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

    with patch("app.webhooks.get_mini", AsyncMock(return_value=None)) as get_mini_mock:
        with patch("app.webhooks.get_pr_diff", AsyncMock()) as get_diff:
            with patch("app.webhooks.get_pr_changed_files", AsyncMock()) as get_files:
                with patch("app.webhooks.get_review_prediction", AsyncMock()) as get_prediction:
                    with patch("app.webhooks.post_pr_review", AsyncMock()) as post_review:
                        await handle_pull_request_opened(payload)

    get_mini_mock.assert_awaited_once_with("allie")
    get_diff.assert_not_awaited()
    get_files.assert_not_awaited()
    get_prediction.assert_not_awaited()
    post_review.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_pull_request_opened_uses_permission_hints_for_author_model():
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

    permission_lookup = AsyncMock(side_effect=["read", "admin"])

    with patch(
        "app.webhooks.get_pr_requested_reviewers",
        AsyncMock(return_value=[{"login": "allie", "type": "User", "site_admin": False}]),
    ):
        with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="diff --git a/x b/x")):
            with patch(
                "app.webhooks.get_pr_changed_files",
                AsyncMock(return_value=["app/retry.py"]),
            ):
                with patch("app.webhooks.get_repo_collaborator_permission", permission_lookup):
                    with patch(
                        "app.webhooks.get_mini",
                        AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                    ):
                        with patch(
                            "app.webhooks.get_review_prediction",
                            AsyncMock(
                                return_value={
                                    "version": "review_prediction_v1",
                                    "delivery_policy": {"author_model": "junior_peer"},
                                    "expressed_feedback": {
                                        "summary": "Needs follow-up.",
                                        "approval_state": "comment",
                                        "comments": [],
                                    },
                                }
                            ),
                        ) as get_prediction:
                            with patch(
                                "app.webhooks.render_review_prediction",
                                return_value="Needs follow-up.",
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


# ---------------------------------------------------------------------------
# Outcome-capture webhook handlers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_calls_trusted_endpoint(monkeypatch):
    """A thumbs-up reaction on a mini comment → PATCH review-cycles with confirmed."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    # Comment body that matches the mini review header pattern
    mini_comment_body = (
        "### Review by @allie's mini\n\n"
        "**Blocker** `sec-1`: Please sanitize this input. Why: SQL injection risk."
    )

    payload = {
        "action": "created_reaction",
        "comment": {
            "id": 999,
            "body": mini_comment_body,
            "in_reply_to_id": None,
        },
        "reaction": {"content": "+1"},
        "pull_request": {"number": 42},
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "sender": {"login": "pr-author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    record_outcome.assert_awaited_once()
    kwargs = record_outcome.await_args.kwargs
    assert kwargs["mini_id"] == "mini-allie"
    assert kwargs["owner"] == "octo-org"
    assert kwargs["repo"] == "hello-world"
    assert kwargs["pr_number"] == 42
    assert kwargs["reviewer_login"] == "allie"
    assert kwargs["disposition"] == "confirmed"
    assert kwargs["trigger"] == "reaction:+1"
    assert kwargs["issue_key"] == "sec-1"


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_with_multi_comment_body_does_not_assume_first_key(monkeypatch):
    """Multi-key review bodies should not default to the first key for reaction events."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    multi_comment_body = (
        "### Review by @allie's mini\n\n"
        "**Blocker** `sec-1`: Please sanitize input. Why: SQL injection risk.\n"
        "**Note** `style-2`: Consider renaming this variable."
    )
    payload = {
        "action": "created_reaction",
        "comment": {"id": 999, "body": multi_comment_body},
        "reaction": {"content": "+1"},
        "pull_request": {"number": 42},
        "repository": {"owner": {"login": "octo-org"}, "name": "hello-world"},
        "sender": {"login": "pr-author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    record_outcome.assert_awaited_once()
    kwargs = record_outcome.await_args.kwargs
    assert kwargs["issue_key"] == "unknown"
    assert kwargs["outcome_capture_context"]["issue_keys"] == ["sec-1", "style-2"]


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_negative_reaction(monkeypatch):
    """A thumbs-down reaction → overpredicted disposition."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    mini_comment_body = (
        "### Review by @allie's mini\n\n"
        "**Note** `style-2`: Consider renaming this variable. Why: clarity."
    )
    payload = {
        "action": "created_reaction",
        "comment": {"id": 100, "body": mini_comment_body},
        "reaction": {"content": "-1"},
        "pull_request": {"number": 7},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "dev", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    kwargs = record_outcome.await_args.kwargs
    assert kwargs["disposition"] == "overpredicted"


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_unknown_recorded(monkeypatch):
    """A no-signal reaction (eyes) is persisted as explicit unknown."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    mini_comment_body = "### Review by @allie's mini\n\n**Note** `perf-1`: Cache this."
    payload = {
        "action": "created_reaction",
        "comment": {"id": 100, "body": mini_comment_body},
        "reaction": {"content": "eyes"},
        "pull_request": {"number": 7},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "dev", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    record_outcome.assert_awaited_once()
    kwargs = record_outcome.await_args.kwargs
    assert kwargs["disposition"] == "unknown"
    assert kwargs["trigger"] == "reaction:eyes"
    assert kwargs["issue_key"] == "perf-1"
    assert kwargs["outcome_capture_context"]["maps_to_predicted_suggestion"] is True


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_flag_off_skips(monkeypatch):
    """When GH_APP_OUTCOME_CAPTURE is off, the handler silently no-ops."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "false")

    payload = {
        "action": "created_reaction",
        "comment": {"id": 100, "body": "### Review by @allie's mini\n\n**Note** `x-1`: Foo."},
        "reaction": {"content": "+1"},
        "pull_request": {"number": 1},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "dev", "type": "User"},
    }

    with patch("app.webhooks.get_mini", AsyncMock()) as get_mini_mock:
        with patch("app.webhooks.record_comment_outcome", AsyncMock()) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    get_mini_mock.assert_not_awaited()
    record_outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_pr_review_comment_reaction_non_mini_comment_skips(monkeypatch):
    """Reactions on non-mini comments (no header) are silently ignored."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    payload = {
        "action": "created_reaction",
        "comment": {"id": 100, "body": "LGTM overall"},
        "reaction": {"content": "+1"},
        "pull_request": {"number": 1},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "dev", "type": "User"},
    }

    with patch("app.webhooks.get_mini", AsyncMock()) as get_mini_mock:
        with patch("app.webhooks.record_comment_outcome", AsyncMock()) as record_outcome:
            await handle_pr_review_comment_reaction(payload)

    get_mini_mock.assert_not_awaited()
    record_outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_confirmed(monkeypatch):
    """An agreeing reply in a mini-comment thread → confirmed disposition."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    original_body = (
        "### Review by @allie's mini\n\n"
        "**Blocker** `null-2`: Add a null check here. Why: NPE risk."
    )
    payload = {
        "action": "created",
        "comment": {
            "id": 200,
            "body": "Good point, fixed!",
            "in_reply_to_id": 100,
            "original_body": original_body,
        },
        "pull_request": {"number": 15},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "pr-author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_thread_reply(payload)

    record_outcome.assert_awaited_once()
    kwargs = record_outcome.await_args.kwargs
    assert kwargs["disposition"] == "confirmed"
    assert kwargs["issue_key"] == "null-2"
    assert kwargs["reviewer_login"] == "allie"


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_maps_to_specific_issue_in_multi_comment_body(monkeypatch):
    """Reply quoting one issue in a multi-comment body maps to that specific key."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    original_body = (
        "### Review by @allie's mini\n\n"
        "**Blocker** `sec-1`: Validate input length. Why: NPE risk.\n"
        "**Question** `auth-2`: Should we include retry count? Why: Observability."
    )
    payload = {
        "action": "created",
        "comment": {
            "id": 205,
            "body": "> **Question** `auth-2`: Should we include retry count?\n\nFixed.",
            "in_reply_to_id": 100,
            "original_body": original_body,
        },
        "pull_request": {"number": 16},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "pr-author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_thread_reply(payload)

    kwargs = record_outcome.await_args.kwargs
    assert kwargs["issue_key"] == "auth-2"
    assert kwargs["outcome_capture_context"]["mapped_issue_key"] == "auth-2"
    assert kwargs["outcome_capture_context"]["issue_keys"] == ["sec-1", "auth-2"]


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_disagreement(monkeypatch):
    """A disagreeing reply → overpredicted disposition."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    original_body = (
        "### Review by @allie's mini\n\n"
        "**Note** `style-3`: Use a more descriptive name."
    )
    payload = {
        "action": "created",
        "comment": {
            "id": 201,
            "body": "I disagree — the name is clear in context.",
            "in_reply_to_id": 100,
            "original_body": original_body,
        },
        "pull_request": {"number": 15},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_thread_reply(payload)

    kwargs = record_outcome.await_args.kwargs
    assert kwargs["disposition"] == "overpredicted"


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_deferred(monkeypatch):
    """An explicit follow-up reply → deferred disposition for ignored memory."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    original_body = (
        "### Review by @allie's mini\n\n"
        "**Note** `docs-1`: Add a README note."
    )
    payload = {
        "action": "created",
        "comment": {
            "id": 202,
            "body": "Let's defer this to a follow-up PR.",
            "in_reply_to_id": 100,
            "original_body": original_body,
        },
        "pull_request": {"number": 15},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_thread_reply(payload)

    kwargs = record_outcome.await_args.kwargs
    assert kwargs["disposition"] == "deferred"
    assert kwargs["issue_key"] == "docs-1"


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_unknown_recorded(monkeypatch):
    """Neutral replies are captured as unknown rather than inferred."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    original_body = (
        "### Review by @allie's mini\n\n"
        "**Note** `style-3`: Use a more descriptive name."
    )
    payload = {
        "action": "created",
        "comment": {
            "id": 203,
            "body": "Interesting observation.",
            "in_reply_to_id": 100,
            "original_body": original_body,
        },
        "pull_request": {"number": 15},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "author", "type": "User"},
    }

    with patch(
        "app.webhooks.get_mini",
        AsyncMock(return_value={"id": "mini-allie", "username": "allie"}),
    ):
        with patch(
            "app.webhooks.record_comment_outcome",
            AsyncMock(return_value=True),
        ) as record_outcome:
            await handle_pr_review_thread_reply(payload)

    kwargs = record_outcome.await_args.kwargs
    assert kwargs["disposition"] == "unknown"
    assert kwargs["issue_key"] == "style-3"


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_not_a_reply_skips(monkeypatch):
    """Top-level review comments (no in_reply_to_id) are not outcome-captured."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "true")

    payload = {
        "action": "created",
        "comment": {
            "id": 300,
            "body": "Looks good.",
            "in_reply_to_id": None,
        },
        "pull_request": {"number": 10},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "author", "type": "User"},
    }

    with patch("app.webhooks.record_comment_outcome", AsyncMock()) as record_outcome:
        await handle_pr_review_thread_reply(payload)

    record_outcome.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_pr_review_thread_reply_flag_off_skips(monkeypatch):
    """Handler is gated by GH_APP_OUTCOME_CAPTURE flag."""
    monkeypatch.setenv("GH_APP_OUTCOME_CAPTURE", "false")

    payload = {
        "action": "created",
        "comment": {"id": 400, "body": "Fixed!", "in_reply_to_id": 99, "original_body": ""},
        "pull_request": {"number": 10},
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "sender": {"login": "author", "type": "User"},
    }

    with patch("app.webhooks.record_comment_outcome", AsyncMock()) as record_outcome:
        await handle_pr_review_thread_reply(payload)

    record_outcome.assert_not_awaited()


# ---------------------------------------------------------------------------
# MINI-30: Idempotency helpers unit tests
# ---------------------------------------------------------------------------


def test_review_already_posted_returns_false_when_no_marker():
    """No SHA marker → never considered already posted."""
    reviews = [{"body": "Some old review text without a marker.", "user": {"login": "bot"}}]
    assert not _review_already_posted(reviews, reviewer_login="allie", head_sha=None)


def test_review_already_posted_returns_true_when_marker_present():
    marker = "<!-- minis-review:allie:abc1234 -->"
    reviews = [{"body": f"Review body\n\n{marker}", "user": {"login": "bot"}}]
    assert _review_already_posted(reviews, reviewer_login="allie", head_sha="abc1234")


def test_review_already_posted_returns_false_for_different_sha():
    marker = "<!-- minis-review:allie:abc1234 -->"
    reviews = [{"body": f"Review body\n\n{marker}", "user": {"login": "bot"}}]
    assert not _review_already_posted(reviews, reviewer_login="allie", head_sha="def5678")


def test_bot_reviews_for_reviewer_filters_by_login_and_signature():
    reviews = [
        {
            "id": 1,
            "user": {"login": "minis-app[bot]"},
            "body": "### Review by @allie's mini\n\nLGTM",
            "state": "COMMENTED",
        },
        {
            "id": 2,
            "user": {"login": "other-bot"},
            "body": "### Review by @allie's mini\n\nLGTM",
            "state": "COMMENTED",
        },
        {
            "id": 3,
            "user": {"login": "minis-app[bot]"},
            "body": "Unrelated review comment",
            "state": "COMMENTED",
        },
    ]
    result = _bot_reviews_for_reviewer(reviews, reviewer_login="allie", bot_login="minis-app[bot]")
    assert len(result) == 1
    assert result[0]["id"] == 1


@pytest.mark.asyncio
async def test_synchronize_supersedes_prior_bot_review_and_adds_updated_prefix():
    """On synchronize, prior bot reviews are dismissed and [Updated — sha] is prepended."""
    prior_review_id = 99
    prior_sha = "old1234"
    new_sha = "new5678"
    prior_marker = f"<!-- minis-review:allie:{prior_sha} -->"
    prior_review = {
        "id": prior_review_id,
        "user": {"login": "minis-app[bot]"},
        "body": f"### Review by @allie's mini\n\nLGTM\n\n{prior_marker}",
        "state": "COMMENTED",
    }

    payload = {
        "action": "synchronize",
        "pull_request": {
            "number": 7,
            "title": "Add retry logic",
            "body": "",
            "html_url": "https://github.com/org/repo/pull/7",
            "head": {"sha": new_sha},
            "author_association": "MEMBER",
            "user": {"login": "dev"},
        },
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "installation": {"id": 1},
    }

    prediction = {
        "version": "review_prediction_v1",
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
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
            "teaching_mode": False,
            "shield_author_from_noise": True,
            "rationale": "",
        },
        "expressed_feedback": {
            "summary": "Looks good overall.",
            "approval_state": "comment",
            "comments": [],
        },
    }

    dismiss_mock = AsyncMock(return_value={})

    with patch(
        "app.webhooks.get_pr_requested_reviewers",
        AsyncMock(return_value=[{"login": "allie", "type": "User", "site_admin": False}]),
    ):
        with patch("app.webhooks.list_pr_reviews", AsyncMock(return_value=[prior_review])):
            with patch("app.webhooks.get_pr_diff", AsyncMock(return_value="")):
                with patch("app.webhooks.get_pr_changed_files", AsyncMock(return_value=[])):
                    with patch(
                        "app.webhooks.get_repo_collaborator_permission",
                        AsyncMock(return_value=None),
                    ):
                        with patch(
                            "app.webhooks.get_mini",
                            AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
                        ):
                            with patch(
                                "app.webhooks.get_review_prediction",
                                AsyncMock(return_value=prediction),
                            ):
                                with patch("app.webhooks.dismiss_pr_review", dismiss_mock):
                                    with patch(
                                        "app.webhooks.post_pr_review",
                                        AsyncMock(return_value={"id": 100, "state": "COMMENTED"}),
                                    ) as post_review:
                                        with patch(
                                            "app.webhooks.record_review_prediction",
                                            AsyncMock(return_value=True),
                                        ):
                                            await handle_pull_request_opened(payload)

    # Prior COMMENTED review should have been dismissed
    dismiss_mock.assert_awaited_once()
    dismiss_args = dismiss_mock.await_args
    # review_id is the 5th positional arg or a keyword
    positional_ids = [a for a in dismiss_args.args if a == prior_review_id]
    assert positional_ids or dismiss_args.kwargs.get("review_id") == prior_review_id

    # New review body should contain [Updated — sha prefix]
    posted_body = post_review.await_args.kwargs["body"]
    assert f"[Updated — {new_sha[:7]}]" in posted_body
    # New idempotency marker for new SHA should be present
    assert f"<!-- minis-review:allie:{new_sha} -->" in posted_body


@pytest.mark.asyncio
async def test_rapid_push_skips_list_reviews_when_sha_cached():
    """Second invocation for the same SHA uses in-memory cache to skip the API call."""
    head_sha = "abc1234"
    cache_key = (1, "org", "repo", 7, "allie")

    # Pre-populate cache as if we already posted this review
    _last_posted_sha_cache[cache_key] = head_sha

    payload = {
        "action": "synchronize",
        "pull_request": {
            "number": 7,
            "title": "Add retry logic",
            "body": "",
            "html_url": "https://github.com/org/repo/pull/7",
            "head": {"sha": head_sha},
            "author_association": "MEMBER",
            "user": {"login": "dev"},
        },
        "repository": {"owner": {"login": "org"}, "name": "repo"},
        "installation": {"id": 1},
    }

    with patch(
        "app.webhooks.get_pr_requested_reviewers",
        AsyncMock(return_value=[{"login": "allie", "type": "User", "site_admin": False}]),
    ):
        with patch("app.webhooks.list_pr_reviews", AsyncMock(return_value=[])) as list_reviews:
            with patch(
                "app.webhooks.get_mini",
                AsyncMock(return_value={"id": "mini-1", "username": "allie"}),
            ):
                with patch("app.webhooks.post_pr_review", AsyncMock()) as post_review:
                    await handle_pull_request_opened(payload)

    list_reviews.assert_not_awaited()
    post_review.assert_not_awaited()


# ---------------------------------------------------------------------------
# MINI-46: Heuristic inline comment tests
# ---------------------------------------------------------------------------


def test_build_inline_review_comments_returns_explicit_location():
    """Explicit path+line from prediction is used directly."""
    from app.review import build_inline_review_comments

    prediction = {
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
        },
        "expressed_feedback": {
            "approval_state": "comment",
            "summary": "",
            "comments": [
                {
                    "type": "blocker",
                    "summary": "Fix the retry loop.",
                    "rationale": "",
                    "path": "src/retry.py",
                    "line": 10,
                    "side": "RIGHT",
                }
            ],
        },
    }
    comments = build_inline_review_comments(
        prediction,
        reviewer_login="allie",
        changed_files=["src/retry.py"],
    )
    assert len(comments) == 1
    assert comments[0]["path"] == "src/retry.py"
    assert comments[0]["line"] == 10


def test_build_inline_review_comments_heuristic_matches_filename():
    """Comments mentioning a changed filename are attached to line 1 via heuristic."""
    from app.review import build_inline_review_comments

    prediction = {
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
        },
        "expressed_feedback": {
            "approval_state": "comment",
            "summary": "",
            "comments": [
                {
                    "type": "note",
                    "summary": "The handler in utils.py could use a constant here.",
                    "rationale": "",
                    # No path/line supplied — should fall back to heuristic
                }
            ],
        },
    }
    comments = build_inline_review_comments(
        prediction,
        reviewer_login="allie",
        changed_files=["src/utils.py", "src/main.py"],
    )
    assert len(comments) == 1
    assert comments[0]["path"] == "src/utils.py"
    assert comments[0]["line"] == 1
    assert comments[0]["side"] == "RIGHT"


def test_build_inline_review_comments_heuristic_no_match_is_skipped():
    """Comments with no file mention are skipped when heuristic can't match."""
    from app.review import build_inline_review_comments

    prediction = {
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
        },
        "expressed_feedback": {
            "approval_state": "comment",
            "summary": "",
            "comments": [
                {
                    "type": "note",
                    "summary": "General architecture concern with no file reference.",
                    "rationale": "",
                }
            ],
        },
    }
    comments = build_inline_review_comments(
        prediction,
        reviewer_login="allie",
        changed_files=["src/utils.py"],
    )
    # "utils.py" is not mentioned in the comment text
    assert comments == []


def test_build_inline_review_comments_heuristic_matches_basename():
    """Heuristic also matches on the basename of a path."""
    from app.review import build_inline_review_comments

    prediction = {
        "prediction_available": True,
        "mode": "llm",
        "unavailable_reason": None,
        "private_assessment": {
            "blocking_issues": [],
            "non_blocking_issues": [],
            "open_questions": [],
            "positive_signals": [],
        },
        "expressed_feedback": {
            "approval_state": "comment",
            "summary": "",
            "comments": [
                {
                    "type": "note",
                    "summary": "The logic in pipeline.py needs attention here.",
                    "rationale": "",
                }
            ],
        },
    }
    comments = build_inline_review_comments(
        prediction,
        reviewer_login="allie",
        changed_files=["backend/app/synthesis/pipeline.py"],
    )
    assert len(comments) == 1
    assert comments[0]["path"] == "backend/app/synthesis/pipeline.py"
