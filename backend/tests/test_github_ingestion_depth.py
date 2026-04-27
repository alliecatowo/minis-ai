"""Depth and truncation tests for GitHub ingestion."""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest

from app.ingestion import github as github_ingestion
from app.plugins.sources.github import GitHubSource


def _response(url: str, body: dict[str, Any] | list[dict[str, Any]]) -> httpx.Response:
    request = httpx.Request("GET", f"https://api.github.com{url}" if url.startswith("/") else url)
    return httpx.Response(200, json=body, request=request)


async def _fake_gh_request(client: httpx.AsyncClient, method: str, url: str, **kw) -> httpx.Response:
    del client, method
    params = kw.get("params") or {}
    payload = kw.get("json") or {}

    if url == "/graphql":
        query = str(payload.get("query", ""))
        if "pullRequestReviewContributions" in query:
            return _response(
                url,
                {
                    "data": {
                        "user": {
                            "contributionsCollection": {
                                "pullRequestReviewContributions": {
                                    "nodes": [],
                                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                                }
                            }
                        }
                    }
                },
            )
        return _response(url, {"data": {"user": {"repositories": {"nodes": []}}}})

    if url.startswith("/users/tester") and not url.endswith("/repos") and "/events" not in url:
        return _response(url, {"login": "tester", "id": 1})

    if url == "/users/tester/repos":
        return _response(url, [])

    if url == "/search/commits":
        return _response(url, {"items": []})

    if url == "/search/issues":
        query = str(params.get("q", ""))
        page = int(params.get("page", "1"))
        if "commenter:" in query:
            return _response(url, {"items": []})

        start = (page - 1) * 100 + 1
        if start > 300:
            return _response(url, {"items": []})

        items = []
        for number in range(start, start + 100):
            items.append(
                {
                    "id": number,
                    "number": number,
                    "node_id": f"PR_node_{number}",
                    "repository_url": "https://api.github.com/repos/owner/repo",
                    "html_url": f"https://github.com/owner/repo/pull/{number}",
                    "title": f"PR {number}",
                    "body": "B" * 9000,
                    "state": "open",
                    "created_at": "2026-04-01T00:00:00Z",
                    "user": {"login": "tester"},
                }
            )
        return _response(url, {"items": items})

    if url == "/users/tester/events":
        return _response(url, [])

    if url == "/users/tester/starred":
        return _response(url, [])

    if url == "/users/tester/gists":
        return _response(url, [])

    issue_match = re.match(r"/repos/owner/repo/issues/(\d+)/comments", url)
    if issue_match:
        number = int(issue_match.group(1))
        return _response(
            url,
            [
                {
                    "id": number * 10 + 1,
                    "body": f"issue comment {number}",
                    "created_at": "2026-04-01T00:00:00Z",
                    "html_url": f"https://github.com/owner/repo/pull/{number}#issuecomment-{number * 10 + 1}",
                    "issue_url": f"https://api.github.com/repos/owner/repo/issues/{number}",
                    "user": {"login": "reviewer"},
                }
            ],
        )

    review_match = re.match(r"/repos/owner/repo/pulls/(\d+)/comments", url)
    if review_match:
        number = int(review_match.group(1))
        return _response(
            url,
            [
                {
                    "id": number * 100 + 1,
                    "body": f"review comment {number}",
                    "path": "src/main.py",
                    "line": 42,
                    "side": "RIGHT",
                    "diff_hunk": "D" * 5000,
                    "created_at": "2026-04-01T00:00:00Z",
                    "html_url": f"https://github.com/owner/repo/pull/{number}#discussion_r{number * 100 + 1}",
                    "pull_request_url": f"https://api.github.com/repos/owner/repo/pulls/{number}",
                    "user": {"login": "reviewer"},
                }
            ],
        )

    reviews_match = re.match(r"/repos/owner/repo/pulls/(\d+)/reviews", url)
    if reviews_match:
        return _response(url, [])

    commits_match = re.match(r"/repos/owner/repo/pulls/(\d+)/commits", url)
    if commits_match:
        number = int(commits_match.group(1))
        return _response(
            url,
            [
                {"sha": f"{number:04d}a"},
                {"sha": f"{number:04d}b"},
            ],
        )

    raise AssertionError(f"Unexpected URL in fake gh_request: {url}")


@pytest.mark.asyncio
async def test_github_ingestion_depth(monkeypatch: pytest.MonkeyPatch):
    async def _graphql_fallback(
        client: httpx.AsyncClient,
        username: str,
        top_n: int = 100,
    ) -> None:
        del client, username, top_n
        return None

    monkeypatch.setattr(github_ingestion, "gh_request", _fake_gh_request)
    monkeypatch.setattr(github_ingestion, "fetch_user_repos_graphql", _graphql_fallback)

    github_data = await github_ingestion.fetch_github_data("tester")
    assert len(github_data.pull_requests) == 300

    source = GitHubSource()
    async def _fetch_cached(_identifier: str):
        return github_data

    monkeypatch.setattr("app.plugins.sources.github.fetch_github_data", _fetch_cached)

    all_items = [
        item async for item in source.fetch_items("tester", "mini-1", None, since_external_ids=set())
    ]

    assert len(all_items) >= 300

    review_items = [item for item in all_items if item.item_type == "review"]
    assert review_items
    assert review_items[0].metadata["file_path"] == "src/main.py"
    assert len(review_items[0].metadata["diff_hunk"]) == 4000

    pr_items = [item for item in all_items if item.item_type == "pr"]
    assert pr_items
    assert len(pr_items[0].raw_body or "") == 8000

    skipped_pr_ids = {f"pr:owner/repo#{n}" for n in range(1, 51)}
    incremental_items = [
        item
        async for item in source.fetch_items(
            "tester",
            "mini-1",
            None,
            since_external_ids=skipped_pr_ids,
        )
    ]

    incremental_prs = [item for item in incremental_items if item.item_type == "pr"]
    assert len(incremental_prs) == 250


@pytest.mark.asyncio
async def test_github_ingestion_new_surfaces(monkeypatch: pytest.MonkeyPatch):
    async def _gh_request_new_surfaces(
        client: httpx.AsyncClient, method: str, url: str, **kw
    ) -> httpx.Response:
        del client
        params = kw.get("params") or {}
        payload = kw.get("json") or {}

        if method == "POST" and url == "/graphql":
            query = str(payload.get("query", ""))
            if "pullRequestReviewContributions" in query:
                return _response(
                    url,
                    {
                        "data": {
                            "user": {
                                "contributionsCollection": {
                                    "pullRequestReviewContributions": {
                                        "nodes": [
                                            {
                                                "pullRequest": {
                                                    "number": 7,
                                                    "repository": {
                                                        "owner": {"login": "owner"},
                                                        "name": "repo",
                                                    },
                                                },
                                                "pullRequestReview": {
                                                    "id": "PRR_77",
                                                    "body": "Looks good overall.",
                                                    "state": "APPROVED",
                                                    "submittedAt": "2026-04-01T00:00:00Z",
                                                    "comments": {
                                                        "nodes": [
                                                            {
                                                                "id": "C1",
                                                                "body": "nit: rename this var",
                                                                "path": "src/main.py",
                                                                "diffHunk": "@@ -1 +1 @@",
                                                                "line": 10,
                                                                "startLine": 10,
                                                            }
                                                        ]
                                                    },
                                                },
                                            }
                                        ],
                                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                                    }
                                }
                            }
                        }
                    },
                )
            return _response(url, {"data": {"user": {"repositories": {"nodes": []}}}})

        if method == "GET" and url.startswith("/users/tester") and "/events" not in url:
            if url.endswith("/repos"):
                return _response(url, [])
            if url.endswith("/starred"):
                return _response(
                    url,
                    [
                        {
                            "id": 501,
                            "full_name": "owner/repo",
                            "description": "A starred repo.",
                            "topics": ["python", "ml"],
                            "language": "Python",
                            "html_url": "https://github.com/owner/repo",
                            "updated_at": "2026-04-01T00:00:00Z",
                            "stargazers_count": 123,
                        }
                    ],
                )
            if url.endswith("/gists"):
                return _response(
                    url,
                    [
                        {
                            "id": "g1",
                            "description": "handy snippet",
                            "html_url": "https://gist.github.com/tester/g1",
                            "created_at": "2026-04-01T00:00:00Z",
                            "owner": {"login": "tester"},
                            "files": {
                                "snippet.py": {
                                    "filename": "snippet.py",
                                    "raw_url": "https://gist.githubusercontent.com/tester/g1/raw/snippet.py",
                                }
                            },
                        }
                    ],
                )
            return _response(url, {"login": "tester", "id": 1})

        if method == "GET" and url == "https://gist.githubusercontent.com/tester/g1/raw/snippet.py":
            request = httpx.Request("GET", url)
            return httpx.Response(200, text="print('hello gist')", request=request)

        if method == "GET" and url == "/search/commits":
            return _response(
                url,
                {
                    "items": [
                        {
                            "sha": "abc123",
                            "commit": {
                                "message": "feat: add endpoint",
                                "author": {"name": "Tester", "date": "2026-04-01T00:00:00Z"},
                            },
                            "repository": {"full_name": "owner/repo"},
                            "author": {"login": "tester"},
                            "html_url": "https://github.com/owner/repo/commit/abc123",
                        }
                    ]
                },
            )

        if method == "GET" and url == "/repos/owner/repo/commits/abc123":
            return _response(
                url,
                {
                    "sha": "abc123",
                    "repo": "owner/repo",
                    "html_url": "https://github.com/owner/repo/commit/abc123",
                    "commit": {"message": "feat: add endpoint"},
                    "files": [
                        {
                            "filename": "src/main.py",
                            "status": "modified",
                            "additions": 5,
                            "deletions": 1,
                            "changes": 6,
                            "patch": "@@ -1 +1 @@\n-old\n+new",
                        }
                    ],
                },
            )

        if method == "GET" and url == "/search/issues":
            query = str(params.get("q", ""))
            if "author:" in query:
                return _response(
                    url,
                    {
                        "items": [
                            {
                                "id": 7001,
                                "number": 7,
                                "node_id": "PR_node_7",
                                "repository_url": "https://api.github.com/repos/owner/repo",
                                "html_url": "https://github.com/owner/repo/pull/7",
                                "title": "Add handler",
                                "body": "Body",
                                "state": "open",
                                "created_at": "2026-04-01T00:00:00Z",
                                "user": {"login": "tester"},
                            }
                        ]
                    },
                )
            return _response(url, {"items": []})

        if method == "GET" and url == "/repos/owner/repo/issues/7/comments":
            return _response(url, [])

        if method == "GET" and url == "/repos/owner/repo/pulls/7/comments":
            return _response(
                url,
                [
                    {
                        "id": 9001,
                        "body": "Please rename this variable",
                        "path": "src/main.py",
                        "line": 42,
                        "start_line": 41,
                        "side": "RIGHT",
                        "commit_id": "abc123",
                        "diff_hunk": "@@ -40,2 +40,2 @@",
                        "created_at": "2026-04-01T00:00:00Z",
                        "html_url": "https://github.com/owner/repo/pull/7#discussion_r9001",
                        "pull_request_url": "https://api.github.com/repos/owner/repo/pulls/7",
                        "user": {"login": "reviewer"},
                    }
                ],
            )

        if method == "GET" and url == "/repos/owner/repo/pulls/7/reviews":
            return _response(url, [])

        if method == "GET" and url == "/repos/owner/repo/pulls/7/commits":
            return _response(url, [{"sha": "abc123"}])

        if method == "GET" and url == "/users/tester/events":
            return _response(url, [])

        raise AssertionError(f"Unexpected {method} {url}")

    async def _graphql_fallback(
        client: httpx.AsyncClient,
        username: str,
        top_n: int = 100,
    ) -> None:
        del client, username, top_n
        return None

    monkeypatch.setattr(github_ingestion, "gh_request", _gh_request_new_surfaces)
    monkeypatch.setattr(github_ingestion, "fetch_user_repos_graphql", _graphql_fallback)
    monkeypatch.setattr("app.plugins.sources.github.settings.github_max_commits_per_repo", 1)

    github_data = await github_ingestion.fetch_github_data("tester")
    source = GitHubSource()

    async def _fetch_cached(_identifier: str):
        return github_data

    monkeypatch.setattr("app.plugins.sources.github.fetch_github_data", _fetch_cached)

    all_items = [
        item async for item in source.fetch_items("tester", "mini-2", None, since_external_ids=set())
    ]

    review_authored = [item for item in all_items if item.item_type == "review_authored"]
    assert review_authored
    assert review_authored[0].external_id == "review:owner/repo#7/PRR_77"

    inline_comments = [item for item in all_items if item.item_type == "review_comment_inline"]
    assert inline_comments
    assert inline_comments[0].external_id == "inline_comment:owner/repo#7/9001"
    assert inline_comments[0].metadata["file_path"] == "src/main.py"
    assert inline_comments[0].metadata["commit_id"] == "abc123"

    starred = [item for item in all_items if item.item_type == "starred"]
    assert starred
    assert starred[0].external_id == "starred:owner/repo"

    gists = [item for item in all_items if item.item_type == "gist"]
    assert gists
    assert gists[0].external_id == "gist:g1"
    assert "snippet.py" in gists[0].content
    assert "hello gist" in gists[0].content

    commits = [item for item in all_items if item.item_type == "commit"]
    assert commits
    assert commits[0].external_id == "commit:owner/repo@abc123"
    assert len(commits[0].raw_context["diff_hunks"]) <= 8000
    commit_diffs = [item for item in all_items if item.item_type == "commit_diff"]
    assert commit_diffs
    assert commit_diffs[0].external_id == "commit_diff:owner/repo@abc123"

    incremental_commit_skip = [
        item
        async for item in source.fetch_items(
            "tester",
            "mini-2",
            None,
            since_external_ids={"commit:owner/repo@abc123"},
        )
    ]
    assert not [item for item in incremental_commit_skip if item.item_type == "commit"]
