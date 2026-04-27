"""Tests for deeper GitHub ingestion evidence fetches."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app.ingestion import github as github_ingestion
from app.ingestion.github import (
    GitHubData,
    build_timeline_targets,
    fetch_commit_diffs,
    fetch_pr_discussions,
    fetch_pr_reviews,
)


def _response(body: list | dict, link: str | None = None) -> httpx.Response:
    headers = {"Link": link} if link else {}
    return httpx.Response(
        200,
        json=body,
        headers=headers,
        request=httpx.Request("GET", "https://api.github.com/test"),
    )


@pytest.mark.asyncio
async def test_fetch_commit_diffs_fetches_detail_for_commit_repo_pairs():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(
        return_value=_response(
            {
                "sha": "abc123",
                "commit": {"message": "fix bug"},
                "stats": {"additions": 2, "deletions": 1, "total": 3},
                "files": [{"filename": "app.py", "patch": "@@ -1 +1 @@"}],
            }
        )
    )
    commits = [{"sha": "abc123", "repository": {"full_name": "ada/engine"}}]

    diffs = await fetch_commit_diffs(client, commits)

    assert len(diffs) == 1
    assert diffs[0]["sha"] == "abc123"
    assert diffs[0]["repo"] == "ada/engine"
    assert diffs[0]["files"][0]["filename"] == "app.py"
    client.request.assert_awaited_once_with(
        "GET",
        "/repos/ada/engine/commits/abc123",
        params=None,
    )


@pytest.mark.asyncio
async def test_fetch_commit_diffs_skips_commits_without_repo_or_sha():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock()

    diffs = await fetch_commit_diffs(
        client,
        [
            {"sha": "abc123"},
            {"repository": {"full_name": "ada/engine"}},
        ],
    )

    assert diffs == []
    client.request.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_pr_discussions_paginates_issue_and_review_comments():
    client = AsyncMock(spec=httpx.AsyncClient)
    issue_page_1 = _response(
        [{"id": 1, "body": "Question", "user": {"login": "reviewer"}}],
        link='<https://api.github.com/next-issue>; rel="next"',
    )
    issue_page_2 = _response([{"id": 2, "body": "Answer", "user": {"login": "ada"}}])
    review_page_1 = _response(
        [
            {
                "id": 10,
                "body": "Please add a test",
                "user": {"login": "ada"},
                "path": "app.py",
                "line": 7,
                "side": "RIGHT",
                "created_at": "2026-04-01T00:00:00Z",
            },
            {
                "id": 11,
                "in_reply_to_id": 10,
                "body": "Done",
                "user": {"login": "contributor"},
                "path": "app.py",
                "line": 7,
                "created_at": "2026-04-01T00:10:00Z",
            },
        ]
    )
    client.request = AsyncMock(side_effect=[issue_page_1, issue_page_2, review_page_1])
    prs = [
        {
            "number": 42,
            "node_id": "PR_node",
            "repository_url": "https://api.github.com/repos/ada/engine",
            "html_url": "https://github.com/ada/engine/pull/42",
        }
    ]

    issue_threads, review_threads, issue_comments, review_comments = await fetch_pr_discussions(
        client, prs, "ada"
    )

    assert len(issue_threads) == 1
    assert issue_threads[0]["repo"] == "ada/engine"
    assert [c["id"] for c in issue_threads[0]["comments"]] == [1, 2]
    # Flat issue_comments output is filtered to comments authored by the subject.
    assert [c["id"] for c in issue_comments] == [2]

    assert len(review_threads) == 1
    assert review_threads[0]["thread_id"] == "ada/engine#42:10"
    assert review_threads[0]["path"] == "app.py"
    assert [c["id"] for c in review_threads[0]["comments"]] == [10, 11]
    # Flat review_comments output is filtered to comments authored by the subject.
    assert [c["id"] for c in review_comments] == [10]

    first_call = client.request.await_args_list[0]
    assert first_call.args == ("GET", "/repos/ada/engine/issues/42/comments")
    assert first_call.kwargs["params"] == {"per_page": "100"}

    second_call = client.request.await_args_list[1]
    assert second_call.args == ("GET", "https://api.github.com/next-issue")
    assert second_call.kwargs["params"] == {}

    third_call = client.request.await_args_list[2]
    assert third_call.args == ("GET", "/repos/ada/engine/pulls/42/comments")
    assert third_call.kwargs["params"] == {"per_page": "100"}


@pytest.mark.asyncio
async def test_fetch_pr_discussions_skips_prs_without_repo():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock()

    result = await fetch_pr_discussions(client, [{"number": 42}], "ada")

    assert result == ([], [], [], [])
    client.request.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_pr_discussions_skips_zero_comment_surfaces():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock()

    prs = [
        {
            "number": 42,
            "node_id": "PR_node",
            "repository_url": "https://api.github.com/repos/ada/engine",
            "html_url": "https://github.com/ada/engine/pull/42",
            "comments": 0,
            "review_comments": 0,
        }
    ]

    issue_threads, review_threads, issue_comments, review_comments = await fetch_pr_discussions(
        client, prs, "ada"
    )

    assert issue_threads == []
    assert review_threads == []
    assert issue_comments == []
    assert review_comments == []
    client.request.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_issue_discussions_skips_zero_comment_issues():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock()

    issues = [
        {
            "number": 7,
            "repository_url": "https://api.github.com/repos/ada/engine",
            "comments": 0,
            "html_url": "https://github.com/ada/engine/issues/7",
        }
    ]

    issue_threads, issue_comments = await github_ingestion.fetch_issue_discussions(client, issues, "ada")

    assert issue_threads == []
    assert issue_comments == []
    client.request.assert_not_called()


@pytest.mark.asyncio
async def test_get_search_items_paginated_stops_before_github_1000_cap(monkeypatch: pytest.MonkeyPatch):
    seen_pages: list[int] = []

    async def _fake_get(
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str] | None = None,
        *,
        phase: str | None = None,
        stop_reasons: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        del client, url, phase, stop_reasons
        page = int((params or {}).get("page", "1"))
        seen_pages.append(page)
        return {"items": [{"id": page * 100 + i} for i in range(100)], "total_count": 5000}

    monkeypatch.setattr(github_ingestion, "_get", _fake_get)
    stops: list[dict[str, object]] = []

    async with httpx.AsyncClient() as client:
        items = await github_ingestion._get_search_items_paginated(
            client,
            "/search/issues",
            params={"q": "author:ada type:pr"},
            item_cap=5000,
            phase="prs_authored_search",
            stop_reasons=stops,
        )

    assert len(items) == 1000
    assert max(seen_pages) == 10
    assert any(
        stop.get("phase") == "prs_authored_search"
        and stop.get("stop_reason") == "search_result_cap_reached"
        for stop in stops
    )


@pytest.mark.asyncio
async def test_fetch_pr_reviews_preserves_state_timeline_metadata():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(
        return_value=_response(
            [
                {
                    "id": 501,
                    "state": "CHANGES_REQUESTED",
                    "body": "The retry path needs a regression test.",
                    "submitted_at": "2026-04-01T12:00:00Z",
                    "commit_id": "abc123",
                    "user": {"login": "ada"},
                    "html_url": "https://github.com/ada/engine/pull/42#pullrequestreview-501",
                }
            ]
        )
    )
    prs = [
        {
            "number": 42,
            "node_id": "PR_node",
            "repository_url": "https://api.github.com/repos/ada/engine",
            "html_url": "https://github.com/ada/engine/pull/42",
        }
    ]

    reviews = await fetch_pr_reviews(client, prs)

    assert len(reviews) == 1
    assert reviews[0]["id"] == 501
    assert reviews[0]["state"] == "CHANGES_REQUESTED"
    assert reviews[0]["repo"] == "ada/engine"
    assert reviews[0]["pr_number"] == 42
    assert reviews[0]["pr_node_id"] == "PR_node"
    assert reviews[0]["pr_html_url"] == "https://github.com/ada/engine/pull/42"
    client.request.assert_awaited_once_with(
        "GET",
        "/repos/ada/engine/pulls/42/reviews",
        params={"per_page": "100"},
    )


def test_build_timeline_targets_includes_discussion_and_review_surfaces():
    data = GitHubData(
        pull_requests=[
            {
                "number": 42,
                "repository_url": "https://api.github.com/repos/ada/engine",
            }
        ],
        issues=[
            {
                "number": 7,
                "repository_url": "https://api.github.com/repos/ada/engine",
            }
        ],
        pr_review_threads=[
            {
                "thread_id": "review-thread-1",
                "repo": "ada/engine",
                "pr_number": 99,
                "comments": [],
            }
        ],
        issue_threads=[
            {
                "repo": "ada/engine",
                "issue_number": 55,
                "comments": [],
            }
        ],
        pull_request_reviews=[
            {
                "id": 123,
                "repo": "ada/engine",
                "pr_number": 88,
            }
        ],
    )

    targets = build_timeline_targets(data)

    assert ("ada/engine", 42) in targets
    assert ("ada/engine", 7) in targets
    assert ("ada/engine", 99) in targets
    assert ("ada/engine", 55) in targets
    assert ("ada/engine", 88) in targets
