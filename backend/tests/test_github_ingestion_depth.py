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
