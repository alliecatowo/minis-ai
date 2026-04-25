"""Tests for deeper GitHub ingestion evidence fetches."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app.ingestion.github import fetch_commit_diffs, fetch_pr_discussions


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
    client.get = AsyncMock(
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
    client.get.assert_awaited_once_with("/repos/ada/engine/commits/abc123", params=None)


@pytest.mark.asyncio
async def test_fetch_commit_diffs_skips_commits_without_repo_or_sha():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock()

    diffs = await fetch_commit_diffs(
        client,
        [
            {"sha": "abc123"},
            {"repository": {"full_name": "ada/engine"}},
        ],
    )

    assert diffs == []
    client.get.assert_not_called()


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
    client.get = AsyncMock(side_effect=[issue_page_1, issue_page_2, review_page_1])
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
    assert [c["id"] for c in issue_comments] == [2]

    assert len(review_threads) == 1
    assert review_threads[0]["thread_id"] == "ada/engine#42:10"
    assert review_threads[0]["path"] == "app.py"
    assert [c["id"] for c in review_threads[0]["comments"]] == [10, 11]
    assert [c["id"] for c in review_comments] == [10]

    assert client.get.await_args_list[0].args[0] == "/repos/ada/engine/issues/42/comments"
    assert client.get.await_args_list[1].args[0] == "https://api.github.com/next-issue"
    assert client.get.await_args_list[2].args[0] == "/repos/ada/engine/pulls/42/comments"


@pytest.mark.asyncio
async def test_fetch_pr_discussions_skips_prs_without_repo():
    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock()

    result = await fetch_pr_discussions(client, [{"number": 42}], "ada")

    assert result == ([], [], [], [])
    client.get.assert_not_called()
