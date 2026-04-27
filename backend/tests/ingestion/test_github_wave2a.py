from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.ingestion import github as github_ingestion


@pytest.mark.asyncio
async def test_fetch_pr_discussions_records_plan_cap(monkeypatch: pytest.MonkeyPatch):
    async def _fake_get_paginated(
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str] | None = None,
        max_pages: int | None = None,
        item_cap: int | None = None,
        *,
        phase: str,
        stop_reasons: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        del client, url, params, max_pages, item_cap, phase, stop_reasons
        return []

    monkeypatch.setattr(github_ingestion, "_get_paginated", _fake_get_paginated)

    prs = [
        {
            "number": 1,
            "node_id": "PR_1",
            "repository_url": "https://api.github.com/repos/tester/repo",
            "html_url": "https://github.com/tester/repo/pull/1",
        },
        {
            "number": 2,
            "node_id": "PR_2",
            "repository_url": "https://api.github.com/repos/tester/repo",
            "html_url": "https://github.com/tester/repo/pull/2",
        },
    ]
    stops: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        await github_ingestion.fetch_pr_discussions(
            client,
            prs,
            "tester",
            max_prs=1,
            stop_reasons=stops,
        )

    assert any(
        stop.get("phase") == "pr_discussions_plan" and stop.get("stop_reason") == "item_cap_reached"
        for stop in stops
    )


@pytest.mark.asyncio
async def test_fetch_github_data_derives_inline_comments_from_threads(monkeypatch: pytest.MonkeyPatch):
    counters: dict[str, int] = {"review_comments_calls": 0}

    async def _fake_gh_request(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        del client
        params = kwargs.get("params") or {}
        payload = kwargs.get("json") or {}

        if method == "POST" and url == "/graphql":
            query = str(payload.get("query", ""))
            if "pullRequestReviewContributions" in query:
                return httpx.Response(
                    200,
                    json={
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
                    request=httpx.Request(method, "https://api.github.com/graphql"),
                )
            return httpx.Response(
                200,
                json={"data": {"user": {"repositories": {"nodes": []}}}},
                request=httpx.Request(method, "https://api.github.com/graphql"),
            )

        if method == "GET" and url == "/users/tester":
            return httpx.Response(
                200,
                json={"login": "tester", "id": 1},
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url in {"/users/tester/repos", "/search/commits"}:
            payload = [] if url.endswith("/repos") else {"items": []}
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/search/issues":
            query = str(params.get("q", ""))
            if "author:tester type:pr" in query:
                items = [
                    {
                        "id": 701,
                        "number": 7,
                        "node_id": "PR_node_7",
                            "repository_url": "https://api.github.com/repos/tester/repo",
                            "html_url": "https://github.com/tester/repo/pull/7",
                        "title": "PR 7",
                        "state": "open",
                    }
                ]
                return httpx.Response(
                    200,
                    json={"items": items},
                    request=httpx.Request(method, f"https://api.github.com{url}"),
                )
            return httpx.Response(
                200,
                json={"items": []},
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/repos/tester/repo/issues/7/comments":
            return httpx.Response(
                200,
                json=[],
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/repos/tester/repo/pulls/7/comments":
            counters["review_comments_calls"] += 1
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 9001,
                        "body": "Please rename this",
                        "path": "src/main.py",
                        "line": 12,
                        "created_at": "2026-04-01T00:00:00Z",
                        "pull_request_url": "https://api.github.com/repos/tester/repo/pulls/7",
                        "user": {"login": "reviewer"},
                    }
                ],
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url in {
            "/repos/tester/repo/pulls/7/reviews",
            "/repos/tester/repo/pulls/7/commits",
            "/users/tester/events",
            "/users/tester/starred",
            "/users/tester/subscriptions",
            "/users/tester/gists",
        }:
            payload = [{"sha": "abc123"}] if url.endswith("/commits") else []
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/repos/tester/repo/issues/7/timeline":
            return httpx.Response(
                200,
                json=[],
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        raise AssertionError(f"Unexpected {method} {url}")

    monkeypatch.setattr(github_ingestion, "gh_request", _fake_gh_request)

    data = await github_ingestion.fetch_github_data("tester")

    assert counters["review_comments_calls"] == 1
    assert len(data.inline_review_comments) == 1
    assert data.inline_review_comments[0]["id"] == 9001


@pytest.mark.asyncio
async def test_fetch_github_data_adds_non_pr_issues_and_issue_threads(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _fake_gh_request(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        del client
        params = kwargs.get("params") or {}
        payload = kwargs.get("json") or {}

        if method == "POST" and url == "/graphql":
            query = str(payload.get("query", ""))
            if "pullRequestReviewContributions" in query:
                return httpx.Response(
                    200,
                    json={
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
                    request=httpx.Request(method, "https://api.github.com/graphql"),
                )
            return httpx.Response(
                200,
                json={"data": {"user": {"repositories": {"nodes": []}}}},
                request=httpx.Request(method, "https://api.github.com/graphql"),
            )

        if method == "GET" and url in {
            "/users/tester",
            "/users/tester/repos",
            "/search/commits",
            "/users/tester/events",
            "/users/tester/starred",
            "/users/tester/subscriptions",
            "/users/tester/gists",
        }:
            if url == "/users/tester":
                payload = {"login": "tester", "id": 1}
            elif url == "/search/commits":
                payload = {"items": []}
            else:
                payload = []
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/search/issues":
            query = str(params.get("q", ""))
            if "author:tester type:issue" in query:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": 5012,
                                "number": 12,
                                "node_id": "ISSUE_node_12",
                                "repository_url": "https://api.github.com/repos/tester/app",
                                "html_url": "https://github.com/tester/app/issues/12",
                                "title": "Track retry drift",
                                "body": "Need better retry accounting",
                                "state": "open",
                                "user": {"login": "tester"},
                            }
                        ]
                    },
                    request=httpx.Request(method, f"https://api.github.com{url}"),
                )
            return httpx.Response(
                200,
                json={"items": []},
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/repos/tester/app/issues/12/comments":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 12001,
                        "body": "let's ship this behind a flag",
                        "created_at": "2026-04-01T00:00:00Z",
                        "html_url": "https://github.com/tester/app/issues/12#issuecomment-12001",
                        "user": {"login": "tester"},
                    }
                ],
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/repos/tester/app/issues/12/timeline":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 12101,
                        "event": "commented",
                        "created_at": "2026-04-01T00:10:00Z",
                        "actor": {"login": "tester"},
                    }
                ],
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        raise AssertionError(f"Unexpected {method} {url}")

    monkeypatch.setattr(github_ingestion, "gh_request", _fake_gh_request)

    data = await github_ingestion.fetch_github_data("tester")

    assert len(data.issues) == 1
    assert data.issues[0]["number"] == 12
    assert len(data.issue_threads) == 1
    assert data.issue_threads[0]["issue_number"] == 12
    assert any(str(event.get("number")) == "12" for event in data.timeline_events)


@pytest.mark.asyncio
async def test_fetch_github_data_applies_org_policy_in_planning(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(github_ingestion.settings, "github_include_org_data", False)
    monkeypatch.setattr(github_ingestion.settings, "github_org_allowlist", "")

    async def _fake_gh_request(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        del client
        params = kwargs.get("params") or {}
        payload = kwargs.get("json") or {}

        if method == "POST" and url == "/graphql":
            query = str(payload.get("query", ""))
            if "pullRequestReviewContributions" in query:
                return httpx.Response(
                    200,
                    json={
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
                    request=httpx.Request(method, "https://api.github.com/graphql"),
                )
            return httpx.Response(
                200,
                json={"data": {"user": {"repositories": {"nodes": []}}}},
                request=httpx.Request(method, "https://api.github.com/graphql"),
            )

        if method == "GET" and url in {
            "/users/tester",
            "/users/tester/repos",
            "/search/commits",
            "/users/tester/events",
            "/users/tester/starred",
            "/users/tester/subscriptions",
            "/users/tester/gists",
        }:
            if url == "/users/tester":
                payload = {"login": "tester", "id": 1}
            elif url == "/search/commits":
                payload = {"items": []}
            else:
                payload = []
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/search/issues":
            query = str(params.get("q", ""))
            if "author:tester type:pr" in query:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": 7001,
                                "number": 7,
                                "repository_url": "https://api.github.com/repos/tester/app",
                            },
                            {
                                "id": 7002,
                                "number": 8,
                                "repository_url": "https://api.github.com/repos/otherorg/secret",
                            },
                        ]
                    },
                    request=httpx.Request(method, f"https://api.github.com{url}"),
                )
            return httpx.Response(
                200,
                json={"items": []},
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url in {
            "/repos/tester/app/issues/7/comments",
            "/repos/tester/app/pulls/7/comments",
            "/repos/tester/app/pulls/7/reviews",
            "/repos/tester/app/pulls/7/commits",
            "/repos/tester/app/issues/7/timeline",
        }:
            payload = [{"sha": "abc123"}] if url.endswith("/commits") else []
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        raise AssertionError(f"Unexpected {method} {url}")

    monkeypatch.setattr(github_ingestion, "gh_request", _fake_gh_request)

    data = await github_ingestion.fetch_github_data("tester")

    assert len(data.pull_requests) == 1
    assert data.pull_requests[0]["number"] == 7
    assert any(
        stop.get("phase") == "prs_authored_policy" and stop.get("stop_reason") == "org_policy_filtered"
        for stop in data.stop_reasons
    )


@pytest.mark.asyncio
async def test_fetch_github_data_adds_non_authored_commented_issues(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _fake_gh_request(
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        del client
        params = kwargs.get("params") or {}
        payload = kwargs.get("json") or {}

        if method == "POST" and url == "/graphql":
            query = str(payload.get("query", ""))
            if "pullRequestReviewContributions" in query:
                return httpx.Response(
                    200,
                    json={
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
                    request=httpx.Request(method, "https://api.github.com/graphql"),
                )
            return httpx.Response(
                200,
                json={"data": {"user": {"repositories": {"nodes": []}}}},
                request=httpx.Request(method, "https://api.github.com/graphql"),
            )

        if method == "GET" and url in {
            "/users/tester",
            "/users/tester/repos",
            "/search/commits",
            "/users/tester/events",
            "/users/tester/starred",
            "/users/tester/subscriptions",
            "/users/tester/gists",
        }:
            if url == "/users/tester":
                payload = {"login": "tester", "id": 1}
            elif url == "/search/commits":
                payload = {"items": []}
            else:
                payload = []
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/search/issues":
            query = str(params.get("q", ""))
            if "author:tester type:issue" in query:
                return httpx.Response(
                    200,
                    json={"items": []},
                    request=httpx.Request(method, f"https://api.github.com{url}"),
                )
            if "commenter:tester type:issue" in query:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": 8801,
                                "number": 88,
                                "node_id": "ISSUE_node_88",
                                "repository_url": "https://api.github.com/repos/acme/app",
                                "html_url": "https://github.com/acme/app/issues/88",
                                "title": "Tighten policy logging",
                                "body": "Need richer stop telemetry",
                                "state": "open",
                                "user": {"login": "someoneelse"},
                            }
                        ]
                    },
                    request=httpx.Request(method, f"https://api.github.com{url}"),
                )
            return httpx.Response(
                200,
                json={"items": []},
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/repos/acme/app/issues/88/comments":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 8811,
                        "body": "I can take this",
                        "created_at": "2026-04-01T00:00:00Z",
                        "html_url": "https://github.com/acme/app/issues/88#issuecomment-8811",
                        "issue_url": "https://api.github.com/repos/acme/app/issues/88",
                        "user": {"login": "tester"},
                    }
                ],
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        if method == "GET" and url == "/repos/acme/app/issues/88/timeline":
            return httpx.Response(
                200,
                json=[],
                request=httpx.Request(method, f"https://api.github.com{url}"),
            )

        raise AssertionError(f"Unexpected {method} {url}")

    monkeypatch.setattr(github_ingestion.settings, "github_include_org_data", True)
    monkeypatch.setattr(github_ingestion, "gh_request", _fake_gh_request)

    data = await github_ingestion.fetch_github_data("tester")

    assert any(issue.get("number") == 88 for issue in data.issues)
    assert any(thread.get("issue_number") == 88 for thread in data.issue_threads)
    assert any(comment.get("id") == 8811 for comment in data.issue_comments)
