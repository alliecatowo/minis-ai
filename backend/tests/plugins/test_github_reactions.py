"""Tests for GitHub reactions ingestion."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.ingestion.github import GitHubData
from app.plugins.sources.github import GitHubSource


def _make_github_data(
    *,
    pull_requests: list | None = None,
    issues: list | None = None,
    issue_comments: list | None = None,
    inline_review_comments: list | None = None,
) -> GitHubData:
    return GitHubData(
        profile={"login": "testuser"},
        repos=[],
        commits=[],
        pull_requests=pull_requests or [],
        issues=issues or [],
        review_comments=[],
        issue_comments=issue_comments or [],
        pull_request_reviews=[],
        repo_languages={},
        commit_diffs=[],
        pr_review_threads=[],
        issue_threads=[],
        inline_review_comments=inline_review_comments or [],
    )


def _reaction_response(reactions: list[dict]) -> httpx.Response:
    return httpx.Response(200, json=reactions)


def _make_reaction(reaction_id: int, emoji: str, actor: str) -> dict:
    return {
        "id": reaction_id,
        "content": emoji,
        "user": {"login": actor},
        "created_at": "2026-01-15T10:00:00Z",
    }


@pytest.mark.asyncio
async def test_reactions_fetched_for_pr(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")
    monkeypatch.setattr("app.plugins.sources.github.settings.github_max_reaction_targets", 500)

    pr = {
        "number": 42,
        "base": {"repo": {"full_name": "owner/repo"}},
        "title": "My PR",
        "state": "merged",
        "user": {"login": "testuser"},
        "created_at": "2026-01-01T00:00:00Z",
    }
    github_data = _make_github_data(pull_requests=[pr])
    reaction = _make_reaction(999, "+1", "reviewer1")

    mock_gh_request = AsyncMock(return_value=_reaction_response([reaction]))

    with (
        patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=github_data)),
        patch("app.plugins.sources.github.gh_request", new=mock_gh_request),
    ):
        items = [item async for item in GitHubSource().fetch_items("testuser", "mini-1", None)]

    reaction_items = [i for i in items if i.item_type == "reaction"]
    assert len(reaction_items) == 1

    r = reaction_items[0]
    assert r.external_id == "reaction:pr:owner/repo#42/999"
    assert r.source_type == "github"
    assert r.author_id == "reviewer1"

    payload = json.loads(r.content)
    assert payload["emoji"] == "+1"
    assert payload["actor_login"] == "reviewer1"

    assert r.metadata["parent_external_id"] == "pr:owner/repo#42"
    assert r.raw_context["parent_external_id"] == "pr:owner/repo#42"


@pytest.mark.asyncio
async def test_reactions_fetched_for_issue(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")
    monkeypatch.setattr("app.plugins.sources.github.settings.github_max_reaction_targets", 500)

    issue = {
        "number": 7,
        "base": {"repo": {"full_name": "owner/repo"}},
        "repository_url": "https://api.github.com/repos/owner/repo",
        "title": "Bug report",
        "state": "open",
        "user": {"login": "testuser"},
        "created_at": "2026-01-01T00:00:00Z",
    }
    github_data = _make_github_data(issues=[issue])
    reaction = _make_reaction(777, "heart", "fan1")

    mock_gh_request = AsyncMock(return_value=_reaction_response([reaction]))

    with (
        patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=github_data)),
        patch("app.plugins.sources.github.gh_request", new=mock_gh_request),
    ):
        items = [item async for item in GitHubSource().fetch_items("testuser", "mini-1", None)]

    reaction_items = [i for i in items if i.item_type == "reaction"]
    assert len(reaction_items) == 1
    assert reaction_items[0].external_id == "reaction:issue:owner/repo#7/777"
    assert reaction_items[0].metadata["parent_external_id"] == "issue:owner/repo#7"


@pytest.mark.asyncio
async def test_reactions_fetched_for_issue_comment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")
    monkeypatch.setattr("app.plugins.sources.github.settings.github_max_reaction_targets", 500)

    comment = {
        "id": 5001,
        "issue_url": "https://api.github.com/repos/owner/repo/issues/3",
        "body": "LGTM",
        "user": {"login": "testuser"},
        "created_at": "2026-01-01T00:00:00Z",
    }
    github_data = _make_github_data(issue_comments=[comment])
    reaction = _make_reaction(333, "rocket", "backer")

    mock_gh_request = AsyncMock(return_value=_reaction_response([reaction]))

    with (
        patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=github_data)),
        patch("app.plugins.sources.github.gh_request", new=mock_gh_request),
    ):
        items = [item async for item in GitHubSource().fetch_items("testuser", "mini-1", None)]

    reaction_items = [i for i in items if i.item_type == "reaction"]
    assert len(reaction_items) == 1
    assert reaction_items[0].external_id == "reaction:issue_comment:5001/333"
    assert reaction_items[0].metadata["parent_external_id"] == "issue_comment:5001"


@pytest.mark.asyncio
async def test_reaction_cap_enforcement(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")
    # Cap to 2 targets — we have 3 PRs, only 2 should be queried
    monkeypatch.setattr("app.plugins.sources.github.settings.github_max_reaction_targets", 2)

    prs = [
        {
            "number": n,
            "base": {"repo": {"full_name": "owner/repo"}},
            "title": f"PR {n}",
            "state": "open",
            "user": {"login": "testuser"},
            "created_at": "2026-01-01T00:00:00Z",
        }
        for n in [1, 2, 3]
    ]
    github_data = _make_github_data(pull_requests=prs)

    call_count = 0

    async def counting_gh_request(client, method, url, **kw):
        nonlocal call_count
        call_count += 1
        return _reaction_response([])

    with (
        patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=github_data)),
        patch("app.plugins.sources.github.fetch_user_issues", new=AsyncMock(return_value=([], []))),
        patch("app.plugins.sources.github.gh_request", new=counting_gh_request),
    ):
        _ = [item async for item in GitHubSource().fetch_items("testuser", "mini-1", None)]

    assert call_count == 2, f"Expected 2 API calls (capped), got {call_count}"


@pytest.mark.asyncio
async def test_reactions_skipped_when_no_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "")
    monkeypatch.setattr("app.plugins.sources.github.settings.github_max_reaction_targets", 500)

    pr = {
        "number": 1,
        "base": {"repo": {"full_name": "owner/repo"}},
        "title": "PR",
        "state": "open",
        "user": {"login": "testuser"},
        "created_at": "2026-01-01T00:00:00Z",
    }
    github_data = _make_github_data(pull_requests=[pr])
    mock_gh_request = AsyncMock()

    with (
        patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=github_data)),
        patch("app.plugins.sources.github.fetch_user_issues", new=AsyncMock(return_value=([], []))),
        patch("app.plugins.sources.github.gh_request", new=mock_gh_request),
    ):
        items = [item async for item in GitHubSource().fetch_items("testuser", "mini-1", None)]

    mock_gh_request.assert_not_called()
    reaction_items = [i for i in items if i.item_type == "reaction"]
    assert len(reaction_items) == 0


@pytest.mark.asyncio
async def test_reaction_external_id_format(monkeypatch: pytest.MonkeyPatch):
    """external_id includes both parent reference and reaction id for uniqueness."""
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")
    monkeypatch.setattr("app.plugins.sources.github.settings.github_max_reaction_targets", 500)

    pr = {
        "number": 10,
        "base": {"repo": {"full_name": "org/project"}},
        "title": "Feature",
        "state": "open",
        "user": {"login": "testuser"},
        "created_at": "2026-01-01T00:00:00Z",
    }
    reactions = [
        _make_reaction(100, "+1", "alice"),
        _make_reaction(101, "heart", "bob"),
    ]
    github_data = _make_github_data(pull_requests=[pr])

    mock_gh_request = AsyncMock(return_value=_reaction_response(reactions))

    with (
        patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=github_data)),
        patch("app.plugins.sources.github.gh_request", new=mock_gh_request),
    ):
        items = [item async for item in GitHubSource().fetch_items("testuser", "mini-1", None)]

    reaction_items = [i for i in items if i.item_type == "reaction"]
    assert len(reaction_items) == 2

    external_ids = {i.external_id for i in reaction_items}
    assert "reaction:pr:org/project#10/100" in external_ids
    assert "reaction:pr:org/project#10/101" in external_ids
