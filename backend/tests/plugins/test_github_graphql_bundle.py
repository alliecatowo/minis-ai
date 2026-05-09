"""Tests for GraphQL co-fetch bundle functions (W4.1).

Mocks the GraphQL POST response and asserts that the emitted evidence
shape matches what the REST path produces, so downstream consumers
don't see a regression.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.ingestion.github import (
    fetch_pr_bundle_graphql,
    fetch_issue_bundle_graphql,
    _fetch_pr_bundles_graphql,
    _fetch_issue_bundles_graphql,
    _graphql_pr_bundle_enabled,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _graphql_response(data: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _make_pr_graphql_payload(
    *,
    owner: str = "acme",
    repo: str = "widget",
    number: int = 42,
    reviews: list | None = None,
    comments: list | None = None,
    review_threads: list | None = None,
    commits: list | None = None,
) -> dict:
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "id": "PR_kwA",
                    "number": number,
                    "title": "Add feature",
                    "body": "This PR adds a feature.",
                    "state": "MERGED",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-02T00:00:00Z",
                    "mergedAt": "2026-01-02T00:00:00Z",
                    "url": f"https://github.com/{owner}/{repo}/pull/{number}",
                    "author": {"login": "alice"},
                    "reviews": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": reviews or [
                            {
                                "id": "RV_1",
                                "body": "LGTM",
                                "state": "APPROVED",
                                "submittedAt": "2026-01-01T12:00:00Z",
                                "author": {"login": "bob"},
                                "comments": {
                                    "nodes": [
                                        {
                                            "id": "RC_1",
                                            "body": "Nice work",
                                            "path": "src/main.py",
                                            "diffHunk": "@@ -1 +1 @@",
                                            "line": 5,
                                            "startLine": None,
                                            "createdAt": "2026-01-01T12:01:00Z",
                                            "updatedAt": "2026-01-01T12:01:00Z",
                                            "author": {"login": "bob"},
                                        }
                                    ]
                                },
                            }
                        ],
                    },
                    "comments": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": comments or [
                            {
                                "id": "IC_1",
                                "body": "Can you add a test?",
                                "createdAt": "2026-01-01T10:00:00Z",
                                "updatedAt": "2026-01-01T10:00:00Z",
                                "author": {"login": "charlie"},
                            }
                        ],
                    },
                    "reviewComments": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": review_threads or [
                            {
                                "id": "THR_1",
                                "isResolved": False,
                                "comments": {
                                    "nodes": [
                                        {
                                            "id": "TRC_1",
                                            "body": "Why this approach?",
                                            "path": "src/foo.py",
                                            "diffHunk": "@@ -2 +2 @@",
                                            "line": 10,
                                            "startLine": None,
                                            "createdAt": "2026-01-01T11:00:00Z",
                                            "updatedAt": "2026-01-01T11:00:00Z",
                                            "author": {"login": "alice"},
                                            "replyTo": None,
                                        }
                                    ]
                                },
                            }
                        ],
                    },
                    "commits": {
                        "nodes": commits or [
                            {
                                "commit": {
                                    "oid": "abc123",
                                    "message": "feat: add widget",
                                    "committedDate": "2025-12-31T22:00:00Z",
                                    "author": {"name": "Alice", "email": "alice@example.com"},
                                }
                            }
                        ]
                    },
                }
            }
        }
    }


def _make_issue_graphql_payload(
    *,
    owner: str = "acme",
    repo: str = "widget",
    number: int = 7,
    comments: list | None = None,
) -> dict:
    return {
        "data": {
            "repository": {
                "issue": {
                    "id": "I_kwA",
                    "number": number,
                    "title": "Bug: crash on startup",
                    "body": "It crashes when foo.",
                    "state": "CLOSED",
                    "createdAt": "2026-01-01T00:00:00Z",
                    "updatedAt": "2026-01-03T00:00:00Z",
                    "closedAt": "2026-01-03T00:00:00Z",
                    "url": f"https://github.com/{owner}/{repo}/issues/{number}",
                    "author": {"login": "alice"},
                    "comments": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": comments or [
                            {
                                "id": "ISC_1",
                                "body": "Can reproduce.",
                                "createdAt": "2026-01-01T08:00:00Z",
                                "updatedAt": "2026-01-01T08:00:00Z",
                                "author": {"login": "dave"},
                            }
                        ],
                    },
                    "timelineItems": {
                        "nodes": [
                            {
                                "__typename": "ClosedEvent",
                                "createdAt": "2026-01-03T00:00:00Z",
                                "actor": {"login": "alice"},
                            }
                        ]
                    },
                }
            }
        }
    }


# ---------------------------------------------------------------------------
# fetch_pr_bundle_graphql unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_pr_bundle_graphql_happy_path():
    payload = _make_pr_graphql_payload(owner="acme", repo="widget", number=42)
    mock_client = MagicMock(spec=httpx.AsyncClient)

    with patch(
        "app.ingestion.github.gh_request",
        new=AsyncMock(return_value=_graphql_response(payload)),
    ):
        result = await fetch_pr_bundle_graphql(mock_client, "acme", "widget", 42)

    assert result is not None
    assert result["pr"]["number"] == 42
    assert result["pr"]["state"] == "MERGED"
    assert len(result["reviews"]) == 1
    assert result["reviews"][0]["state"] == "APPROVED"
    assert len(result["issue_comments"]) == 1
    assert result["issue_comments"][0]["id"] == "IC_1"
    assert len(result["review_comments"]) == 1
    assert result["review_comments"][0]["comments"][0]["path"] == "src/foo.py"
    assert len(result["commits"]) == 1
    assert result["commits"][0]["sha"] == "abc123"


@pytest.mark.asyncio
async def test_fetch_pr_bundle_graphql_non200_returns_none():
    mock_client = MagicMock(spec=httpx.AsyncClient)

    with patch(
        "app.ingestion.github.gh_request",
        new=AsyncMock(return_value=httpx.Response(404, json={"message": "Not Found"})),
    ):
        result = await fetch_pr_bundle_graphql(mock_client, "acme", "widget", 99)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_pr_bundle_graphql_errors_field_returns_none():
    payload = {"errors": [{"message": "Field 'pullRequest' doesn't exist"}]}
    mock_client = MagicMock(spec=httpx.AsyncClient)

    with patch(
        "app.ingestion.github.gh_request",
        new=AsyncMock(return_value=_graphql_response(payload)),
    ):
        result = await fetch_pr_bundle_graphql(mock_client, "acme", "widget", 42)

    assert result is None


# ---------------------------------------------------------------------------
# fetch_issue_bundle_graphql unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_issue_bundle_graphql_happy_path():
    payload = _make_issue_graphql_payload(owner="acme", repo="widget", number=7)
    mock_client = MagicMock(spec=httpx.AsyncClient)

    with patch(
        "app.ingestion.github.gh_request",
        new=AsyncMock(return_value=_graphql_response(payload)),
    ):
        result = await fetch_issue_bundle_graphql(mock_client, "acme", "widget", 7)

    assert result is not None
    assert result["issue"]["number"] == 7
    assert result["issue"]["state"] == "CLOSED"
    assert len(result["comments"]) == 1
    assert result["comments"][0]["id"] == "ISC_1"
    assert len(result["timeline"]) == 1
    assert result["timeline"][0]["__typename"] == "ClosedEvent"


@pytest.mark.asyncio
async def test_fetch_issue_bundle_graphql_non200_returns_none():
    mock_client = MagicMock(spec=httpx.AsyncClient)

    with patch(
        "app.ingestion.github.gh_request",
        new=AsyncMock(return_value=httpx.Response(500, text="oops")),
    ):
        result = await fetch_issue_bundle_graphql(mock_client, "acme", "widget", 7)

    assert result is None


# ---------------------------------------------------------------------------
# _fetch_pr_bundles_graphql batch orchestration
# ---------------------------------------------------------------------------


def _stub_pr(repo: str = "acme/widget", number: int = 42) -> dict:
    return {
        "number": number,
        "repository_url": f"https://api.github.com/repos/{repo}",
        "node_id": f"PR_{number}",
        "html_url": f"https://github.com/{repo}/pull/{number}",
    }


@pytest.mark.asyncio
async def test_fetch_pr_bundles_graphql_returns_six_tuple():
    pr = _stub_pr()
    payload = _make_pr_graphql_payload()
    mock_client = MagicMock(spec=httpx.AsyncClient)

    with patch(
        "app.ingestion.github.gh_request",
        new=AsyncMock(return_value=_graphql_response(payload)),
    ):
        result = await _fetch_pr_bundles_graphql(mock_client, [pr], "alice")

    it, rt, ic, rc, reviews, commits = result
    # issue thread captured
    assert len(it) == 1
    assert it[0]["pr_number"] == 42
    # review thread captured
    assert len(rt) == 1
    assert rt[0]["path"] == "src/foo.py"
    # reviews list
    assert len(reviews) == 1
    assert reviews[0]["state"] == "APPROVED"
    # commits list
    assert len(commits) == 1
    assert commits[0]["commits"][0]["sha"] == "abc123"


@pytest.mark.asyncio
async def test_fetch_pr_bundles_graphql_falls_back_to_rest_on_none():
    """When GraphQL returns None, the batch function calls REST fallbacks."""
    pr = _stub_pr()
    mock_client = MagicMock(spec=httpx.AsyncClient)

    rest_threads = [{"repo": "acme/widget", "pr_number": 42, "pr_node_id": "PR_42", "html_url": "", "comments": []}]

    with (
        patch(
            "app.ingestion.github.fetch_pr_bundle_graphql",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.ingestion.github.fetch_pr_discussions",
            new=AsyncMock(return_value=(rest_threads, [], [], [])),
        ),
        patch(
            "app.ingestion.github.fetch_pr_reviews",
            new=AsyncMock(return_value=[{"id": "RV_fallback"}]),
        ),
        patch(
            "app.ingestion.github.fetch_pr_commit_lists",
            new=AsyncMock(return_value=[{"repo": "acme/widget", "pr_number": 42, "commits": []}]),
        ),
    ):
        it, rt, ic, rc, reviews, commits = await _fetch_pr_bundles_graphql(
            mock_client, [pr], "alice"
        )

    assert len(it) == 1
    assert reviews[0]["id"] == "RV_fallback"
    assert len(commits) == 1


# ---------------------------------------------------------------------------
# _fetch_issue_bundles_graphql batch orchestration
# ---------------------------------------------------------------------------


def _stub_issue(repo: str = "acme/widget", number: int = 7) -> dict:
    return {
        "number": number,
        "repository_url": f"https://api.github.com/repos/{repo}",
        "node_id": f"I_{number}",
        "html_url": f"https://github.com/{repo}/issues/{number}",
    }


@pytest.mark.asyncio
async def test_fetch_issue_bundles_graphql_returns_two_tuple():
    issue = _stub_issue()
    payload = _make_issue_graphql_payload()
    mock_client = MagicMock(spec=httpx.AsyncClient)

    with patch(
        "app.ingestion.github.gh_request",
        new=AsyncMock(return_value=_graphql_response(payload)),
    ):
        threads, comments = await _fetch_issue_bundles_graphql(mock_client, [issue], "alice")

    assert len(threads) == 1
    assert threads[0]["issue_number"] == 7
    # "alice" didn't comment, so subject comments list is empty
    assert comments == []


@pytest.mark.asyncio
async def test_fetch_issue_bundles_graphql_subject_comment_extracted():
    issue = _stub_issue()
    payload = _make_issue_graphql_payload(
        comments=[
            {
                "id": "ISC_2",
                "body": "I can fix this.",
                "createdAt": "2026-01-01T09:00:00Z",
                "updatedAt": "2026-01-01T09:00:00Z",
                "author": {"login": "alice"},
            }
        ]
    )
    mock_client = MagicMock(spec=httpx.AsyncClient)

    with patch(
        "app.ingestion.github.gh_request",
        new=AsyncMock(return_value=_graphql_response(payload)),
    ):
        threads, comments = await _fetch_issue_bundles_graphql(mock_client, [issue], "alice")

    assert len(threads) == 1
    assert len(comments) == 1
    assert comments[0]["id"] == "ISC_2"


@pytest.mark.asyncio
async def test_fetch_issue_bundles_graphql_falls_back_to_rest_on_none():
    issue = _stub_issue()
    mock_client = MagicMock(spec=httpx.AsyncClient)

    rest_threads = [{"repo": "acme/widget", "issue_number": 7, "comments": []}]

    with (
        patch(
            "app.ingestion.github.fetch_issue_bundle_graphql",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.ingestion.github.fetch_issue_discussions",
            new=AsyncMock(return_value=(rest_threads, [])),
        ),
    ):
        threads, comments = await _fetch_issue_bundles_graphql(mock_client, [issue], "alice")

    assert threads == rest_threads


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


def test_graphql_pr_bundle_enabled_default():
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_GRAPHQL_PR_BUNDLE"}
    with patch.dict(os.environ, env, clear=True):
        assert _graphql_pr_bundle_enabled() is True


def test_graphql_pr_bundle_enabled_explicit_false():
    with patch.dict(os.environ, {"GITHUB_GRAPHQL_PR_BUNDLE": "false"}):
        assert _graphql_pr_bundle_enabled() is False


def test_graphql_pr_bundle_enabled_explicit_true():
    with patch.dict(os.environ, {"GITHUB_GRAPHQL_PR_BUNDLE": "true"}):
        assert _graphql_pr_bundle_enabled() is True
