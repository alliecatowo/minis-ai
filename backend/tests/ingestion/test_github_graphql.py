"""Tests for the GitHub GraphQL repos+languages batched fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app.ingestion.github import fetch_user_repos_graphql


def _make_graphql_response(
    status_code: int = 200,
    body: dict | None = None,
    text: str = "",
) -> httpx.Response:
    """Build a minimal ``httpx.Response`` for GraphQL test stubs."""
    req = httpx.Request("POST", "https://api.github.com/graphql")
    if body is not None:
        return httpx.Response(status_code, json=body, request=req)
    return httpx.Response(status_code, text=text, request=req)


_SAMPLE_NODE = {
    "name": "cool-repo",
    "nameWithOwner": "ada/cool-repo",
    "description": "A cool repo",
    "stargazerCount": 42,
    "pushedAt": "2026-04-01T00:00:00Z",
    "isFork": False,
    "isArchived": False,
    "repositoryTopics": {
        "nodes": [
            {"topic": {"name": "rust"}},
            {"topic": {"name": "compilers"}},
        ]
    },
    "primaryLanguage": {"name": "Rust"},
    "languages": {
        "edges": [
            {"size": 9000, "node": {"name": "Rust"}},
            {"size": 1000, "node": {"name": "Python"}},
        ]
    },
}


@pytest.mark.asyncio
async def test_fetch_user_repos_graphql_happy_path_maps_shape():
    """A normal GraphQL response should map cleanly to REST-shaped dicts."""
    client = AsyncMock()
    client.post.return_value = _make_graphql_response(
        body={"data": {"user": {"repositories": {"nodes": [_SAMPLE_NODE]}}}}
    )

    result = await fetch_user_repos_graphql(client, "ada")

    assert result is not None
    repos, repo_langs = result

    assert len(repos) == 1
    repo = repos[0]
    # Shape matches what REST /users/:login/repos returns (and what
    # fetch_github_data / plugins/sources/github.py downstream consumes).
    assert repo["name"] == "cool-repo"
    assert repo["full_name"] == "ada/cool-repo"
    assert repo["description"] == "A cool repo"
    assert repo["language"] == "Rust"
    assert repo["stargazers_count"] == 42
    assert repo["topics"] == ["rust", "compilers"]
    assert repo["pushed_at"] == "2026-04-01T00:00:00Z"
    assert repo["fork"] is False
    assert repo["archived"] is False

    # repo_languages keyed by full_name (matches REST path behavior).
    assert repo_langs == {"ada/cool-repo": {"Rust": 9000, "Python": 1000}}


@pytest.mark.asyncio
async def test_fetch_user_repos_graphql_uses_post_to_graphql_endpoint():
    """Verifies the request is POSTed to the GraphQL endpoint with the right payload."""
    client = AsyncMock()
    client.post.return_value = _make_graphql_response(
        body={"data": {"user": {"repositories": {"nodes": []}}}}
    )

    await fetch_user_repos_graphql(client, "ada")

    assert client.post.await_count == 1
    call = client.post.await_args
    assert call.args[0] == "https://api.github.com/graphql"
    payload = call.kwargs["json"]
    assert "query" in payload
    assert payload["variables"] == {"login": "ada"}


@pytest.mark.asyncio
async def test_fetch_user_repos_graphql_handles_empty_nodes():
    """An empty ``nodes`` list should yield empty results, not None."""
    client = AsyncMock()
    client.post.return_value = _make_graphql_response(
        body={"data": {"user": {"repositories": {"nodes": []}}}}
    )

    result = await fetch_user_repos_graphql(client, "ada")

    assert result == ([], {})


@pytest.mark.asyncio
async def test_fetch_user_repos_graphql_returns_none_on_errors_array():
    """A GraphQL ``errors`` array in the body should cause a fallback (None)."""
    client = AsyncMock()
    client.post.return_value = _make_graphql_response(
        body={"errors": [{"message": "something broke"}]}
    )

    assert await fetch_user_repos_graphql(client, "ada") is None


@pytest.mark.asyncio
async def test_fetch_user_repos_graphql_returns_none_on_non_200():
    """A non-200 HTTP response should cause a fallback (None)."""
    client = AsyncMock()
    client.post.return_value = _make_graphql_response(status_code=502, text="Bad Gateway")

    assert await fetch_user_repos_graphql(client, "ada") is None


@pytest.mark.asyncio
async def test_fetch_user_repos_graphql_returns_none_on_exception():
    """A network-level exception should be caught and surface as a fallback (None)."""
    client = AsyncMock()
    client.post.side_effect = httpx.ConnectError("boom")

    assert await fetch_user_repos_graphql(client, "ada") is None


@pytest.mark.asyncio
async def test_fetch_user_repos_graphql_returns_none_on_missing_user():
    """A GraphQL ``user: null`` (e.g., user not found) should fall back."""
    client = AsyncMock()
    client.post.return_value = _make_graphql_response(body={"data": {"user": None}})

    assert await fetch_user_repos_graphql(client, "ada") is None


@pytest.mark.asyncio
async def test_fetch_user_repos_graphql_skips_repos_without_languages():
    """Repos with no language edges should still appear in ``repos`` but NOT in ``repo_languages``."""
    node_no_lang = {
        **_SAMPLE_NODE,
        "nameWithOwner": "ada/docs-only",
        "name": "docs-only",
        "primaryLanguage": None,
        "languages": {"edges": []},
    }
    client = AsyncMock()
    client.post.return_value = _make_graphql_response(
        body={"data": {"user": {"repositories": {"nodes": [node_no_lang]}}}}
    )

    result = await fetch_user_repos_graphql(client, "ada")
    assert result is not None
    repos, repo_langs = result
    assert len(repos) == 1
    assert repos[0]["language"] is None
    assert repo_langs == {}


@pytest.mark.asyncio
async def test_fetch_user_repos_graphql_respects_top_n():
    """The ``top_n`` cap should slice the returned nodes."""
    nodes = [
        {**_SAMPLE_NODE, "name": f"repo-{i}", "nameWithOwner": f"ada/repo-{i}"} for i in range(5)
    ]
    client = AsyncMock()
    client.post.return_value = _make_graphql_response(
        body={"data": {"user": {"repositories": {"nodes": nodes}}}}
    )

    result = await fetch_user_repos_graphql(client, "ada", top_n=2)
    assert result is not None
    repos, _ = result
    assert len(repos) == 2
    assert [r["name"] for r in repos] == ["repo-0", "repo-1"]
