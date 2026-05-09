"""Tests for authored non-PR issues + comment thread ingestion."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.ingestion.github import GitHubData
from app.plugins.sources.github import (
    GitHubSource,
    _external_id_for_authored_issue,
    _repo_from_issue_api,
    fetch_user_issues,
)


_GH_BASE = "https://api.github.com"


def _make_search_response(items: list[dict], total: int | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={"total_count": total if total is not None else len(items), "items": items},
    )


def _make_comments_response(comments: list[dict]) -> httpx.Response:
    return httpx.Response(200, json=comments)


def _make_issue(
    number: int,
    repo: str = "testuser/myrepo",
    *,
    is_pr: bool = False,
    state: str = "open",
    author: str = "testuser",
) -> dict:
    # Use a recent date (< 90 days old) so items pass recency-window sampling.
    # Use testuser/myrepo so org-policy filter passes (owner == identifier).
    issue: dict = {
        "number": number,
        "title": f"Issue #{number}",
        "body": f"Body of issue {number}",
        "state": state,
        "user": {"login": author},
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "repository_url": f"{_GH_BASE}/repos/{repo}",
        "created_at": "2026-04-20T00:00:00Z",
        "updated_at": "2026-04-20T00:00:00Z",
        "reactions": {"total_count": 0, "+1": 0, "-1": 0, "heart": 0},
    }
    if is_pr:
        issue["pull_request"] = {"url": f"https://api.github.com/repos/{repo}/pulls/{number}"}
    return issue


def _make_comment(comment_id: int, author: str = "testuser") -> dict:
    return {
        "id": comment_id,
        "body": f"Comment body {comment_id}",
        "user": {"login": author},
        "html_url": f"https://github.com/testuser/myrepo/issues/1#issuecomment-{comment_id}",
        "created_at": "2026-04-20T00:00:00Z",
        "updated_at": "2026-04-20T00:00:00Z",
        "reactions": {"total_count": 0},
    }


def _make_github_data() -> GitHubData:
    return GitHubData(
        profile={"login": "testuser"},
        repos=[],
        commits=[],
        issues=[],
        pull_requests=[],
        review_comments=[],
        issue_comments=[],
        pull_request_reviews=[],
        repo_languages={},
        commit_diffs=[],
        pr_review_threads=[],
        issue_threads=[],
        inline_review_comments=[],
    )


# ── Unit tests for helper functions ─────────────────────────────────────────

def test_external_id_for_authored_issue_with_repo_url():
    issue = {
        "number": 42,
        "repository_url": f"{_GH_BASE}/repos/testuser/myrepo",
    }
    assert _external_id_for_authored_issue(issue) == "issue:testuser/myrepo#42"


def test_external_id_for_authored_issue_missing_repo():
    issue = {"number": 7, "repository_url": ""}
    assert _external_id_for_authored_issue(issue) == "issue:unknown#7"


def test_repo_from_issue_api():
    issue = {"repository_url": f"{_GH_BASE}/repos/alice/proj"}
    assert _repo_from_issue_api(issue) == "alice/proj"


def test_repo_from_issue_api_empty():
    assert _repo_from_issue_api({}) == ""


# ── fetch_user_issues unit tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_user_issues_empty_user(monkeypatch: pytest.MonkeyPatch):
    """Empty search results → no issues, no comments."""
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")

    async def mock_gh_request(client, method, url, **kw):
        return _make_search_response([])

    with patch("app.plugins.sources.github.gh_request", new=AsyncMock(side_effect=mock_gh_request)):
        issues, comments = await fetch_user_issues("nobody", max_issues=200, max_comments_per_issue=50)

    assert issues == []
    assert comments == []


@pytest.mark.asyncio
async def test_fetch_user_issues_filters_prs(monkeypatch: pytest.MonkeyPatch):
    """PR items in search results are silently dropped."""
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")

    call_count = 0

    async def mock_gh_request(client, method, url, **kw):
        nonlocal call_count
        call_count += 1
        if "search/issues" in url:
            return _make_search_response([
                _make_issue(1),            # real issue — kept
                _make_issue(2, is_pr=True),  # PR — dropped
            ])
        # comment endpoint should not be called for PR
        return _make_comments_response([])

    with patch("app.plugins.sources.github.gh_request", new=AsyncMock(side_effect=mock_gh_request)):
        issues, comments = await fetch_user_issues("testuser", max_issues=200, max_comments_per_issue=50)

    assert len(issues) == 1
    assert issues[0]["number"] == 1


@pytest.mark.asyncio
async def test_fetch_user_issues_with_comments(monkeypatch: pytest.MonkeyPatch):
    """Issues have comments; each comment carries parent_external_id."""
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")

    issue = _make_issue(10)
    comment = _make_comment(999)

    async def mock_gh_request(client, method, url, **kw):
        if "search/issues" in url:
            return _make_search_response([issue])
        # issues/{number}/comments endpoint
        return _make_comments_response([comment])

    with patch("app.plugins.sources.github.gh_request", new=AsyncMock(side_effect=mock_gh_request)):
        issues, comments = await fetch_user_issues("testuser", max_issues=200, max_comments_per_issue=50)

    assert len(issues) == 1
    assert len(comments) == 1
    assert comments[0]["parent_external_id"] == "issue:testuser/myrepo#10"
    assert comments[0]["id"] == 999


@pytest.mark.asyncio
async def test_fetch_user_issues_respects_max_issues_cap(monkeypatch: pytest.MonkeyPatch):
    """Cap of 2 stops fetching after 2 issues even if search returns more."""
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")

    async def mock_gh_request(client, method, url, **kw):
        if "search/issues" in url:
            # Return 5 issues — cap should stop at 2
            return _make_search_response([_make_issue(i) for i in range(1, 6)], total=5)
        return _make_comments_response([])

    with patch("app.plugins.sources.github.gh_request", new=AsyncMock(side_effect=mock_gh_request)):
        issues, _ = await fetch_user_issues("testuser", max_issues=2, max_comments_per_issue=50)

    assert len(issues) == 2


# ── Integration tests: fetch_items emits issue + issue_comment evidence ──────

@pytest.mark.asyncio
async def test_fetch_items_emits_issue_and_issue_comment(monkeypatch: pytest.MonkeyPatch):
    """fetch_items yields issue + issue_comment evidence for authored issues."""
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")
    monkeypatch.setattr(
        "app.plugins.sources.github.settings.github_max_issues_authored", 200
    )
    monkeypatch.setattr(
        "app.plugins.sources.github.settings.github_max_issue_comment_threads", 50
    )

    github_data = _make_github_data()
    issue = _make_issue(5)
    comment = _make_comment(111)

    async def mock_gh_request(client, method, url, **kw):
        if "search/issues" in url:
            return _make_search_response([issue])
        if "comments" in url:
            return _make_comments_response([comment])
        return httpx.Response(200, json=[])

    with (
        patch(
            "app.plugins.sources.github.GitHubSource._fetch_with_cache",
            new=AsyncMock(return_value=github_data),
        ),
        patch(
            "app.plugins.sources.github.fetch_github_data",
            new=AsyncMock(return_value=github_data),
        ),
        patch("app.plugins.sources.github.gh_request", new=AsyncMock(side_effect=mock_gh_request)),
        patch(
            "app.plugins.sources.github.get_latest_external_ids",
            new=AsyncMock(return_value=set()),
        ),
    ):
        source = GitHubSource()
        items = [
            item
            async for item in source.fetch_items(
                "testuser", "mini-123", session=None, since_external_ids=set()
            )
        ]

    types = {item.item_type for item in items}
    assert "issue" in types, f"Expected 'issue' in item types, got {types}"
    assert "issue_comment" in types, f"Expected 'issue_comment' in item types, got {types}"

    issue_items = [i for i in items if i.item_type == "issue"]
    assert len(issue_items) >= 1
    assert issue_items[0].external_id == "issue:testuser/myrepo#5"

    comment_items = [i for i in items if i.item_type == "issue_comment"]
    assert len(comment_items) >= 1
    assert comment_items[0].external_id == "issue_comment:111"
    assert comment_items[0].metadata.get("parent_external_id") == "issue:testuser/myrepo#5"


@pytest.mark.asyncio
async def test_fetch_items_skips_seen_issues(monkeypatch: pytest.MonkeyPatch):
    """Issues already in since_external_ids are not re-emitted."""
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "tok")
    monkeypatch.setattr("app.plugins.sources.github.settings.github_max_issues_authored", 200)
    monkeypatch.setattr("app.plugins.sources.github.settings.github_max_issue_comment_threads", 50)

    github_data = _make_github_data()
    issue = _make_issue(99)
    already_seen = {"issue:testuser/myrepo#99"}

    async def mock_gh_request(client, method, url, **kw):
        if "search/issues" in url:
            return _make_search_response([issue])
        return _make_comments_response([])

    with (
        patch(
            "app.plugins.sources.github.GitHubSource._fetch_with_cache",
            new=AsyncMock(return_value=github_data),
        ),
        patch(
            "app.plugins.sources.github.fetch_github_data",
            new=AsyncMock(return_value=github_data),
        ),
        patch("app.plugins.sources.github.gh_request", new=AsyncMock(side_effect=mock_gh_request)),
        patch(
            "app.plugins.sources.github.get_latest_external_ids",
            new=AsyncMock(return_value=set()),
        ),
    ):
        source = GitHubSource()
        items = [
            item
            async for item in source.fetch_items(
                "testuser", "mini-123", session=None, since_external_ids=already_seen
            )
        ]

    issue_items = [i for i in items if i.item_type == "issue" and i.external_id == "issue:testuser/myrepo#99"]
    assert len(issue_items) == 0, "Seen issue should not be re-emitted"
