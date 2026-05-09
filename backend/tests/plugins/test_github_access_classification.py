from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.ingestion.github import GitHubData
from app.plugins.sources.github import GitHubSource


def _github_data_for_repo(repo_full_name: str, *, private: bool) -> GitHubData:
    return GitHubData(
        profile={"login": "tester"},
        repos=[
            {
                "full_name": repo_full_name,
                "private": private,
                "visibility": "private" if private else "public",
            }
        ],
        commits=[
            {
                "sha": "abc123",
                "repository": {"full_name": repo_full_name},
                "commit": {
                    "message": "feat: add guard",
                    "author": {"name": "Tester", "date": "2026-04-01T00:00:00Z"},
                },
                "author": {"login": "tester"},
            }
        ],
        pull_requests=[],
        review_comments=[],
        issue_comments=[],
        pull_request_reviews=[],
        repo_languages={},
        commit_diffs=[],
        pr_review_threads=[],
        issue_threads=[],
    )


@pytest.mark.asyncio
async def test_private_user_repo_is_private_access_classification():
    source = GitHubSource()
    fake_data = _github_data_for_repo("tester/private-repo", private=True)

    with patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=fake_data)):
        items = [item async for item in source.fetch_items("tester", "mini-1", None)]

    commit = next(item for item in items if item.item_type == "commit")
    assert commit.privacy == "private"
    assert commit.access_classification == "private"
    assert commit.source_authorization == "authorized"


@pytest.mark.asyncio
async def test_private_org_repo_is_company_classification_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("app.plugins.sources.github.settings.github_include_org_data", True)

    source = GitHubSource()
    fake_data = _github_data_for_repo("acme/internal-repo", private=True)

    with patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=fake_data)):
        items = [item async for item in source.fetch_items("tester", "mini-1", None)]

    commit = next(item for item in items if item.item_type == "commit")
    assert commit.privacy == "private"
    assert commit.access_classification == "company"
    assert commit.source_authorization == "authorized"


@pytest.mark.asyncio
async def test_authenticated_unknown_repo_defaults_to_company_not_public(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("app.plugins.sources.github.settings.github_include_org_data", True)
    monkeypatch.setattr("app.plugins.sources.github.settings.github_token", "token-123")

    source = GitHubSource()
    fake_data = GitHubData(
        profile={"login": "tester"},
        repos=[],
        reviews_authored=[
            {
                "owner": "acme",
                "repo": "internal-repo",
                "pr_number": 17,
                "review_id": "r17",
                "body": "Ship it",
                "state": "APPROVED",
                "submitted_at": "2026-04-01T00:00:00Z",
                "comments": [],
            }
        ],
    )

    with patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=fake_data)):
        items = [item async for item in source.fetch_items("tester", "mini-1", None)]

    review = next(item for item in items if item.item_type == "review_authored")
    assert review.privacy == "private"
    assert review.access_classification == "company"


@pytest.mark.asyncio
async def test_private_gist_is_private_classification():
    source = GitHubSource()
    fake_data = GitHubData(
        profile={"login": "tester"},
        repos=[],
        gists=[
            {
                "id": "g-private",
                "description": "private snippet",
                "public": False,
                "created_at": "2026-04-01T00:00:00Z",
                "owner": {"login": "tester"},
                "files_enriched": [{"filename": "notes.txt", "content": "secret"}],
            }
        ],
    )

    with patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=fake_data)):
        items = [item async for item in source.fetch_items("tester", "mini-1", None)]

    gist = next(item for item in items if item.item_type == "gist")
    assert gist.privacy == "private"
    assert gist.access_classification == "private"


@pytest.mark.asyncio
async def test_discussion_primitives_and_review_reactions_are_preserved():
    source = GitHubSource()
    fake_data = GitHubData(
        profile={"login": "tester"},
        repos=[
            {
                "full_name": "tester/repo",
                "private": False,
                "visibility": "public",
            }
        ],
        issue_threads=[
            {
                "repo": "tester/repo",
                "issue_number": 12,
                "comments": [
                    {
                        "id": 1201,
                        "body": "Issue discussion note",
                        "created_at": "2026-04-01T00:00:00Z",
                        "html_url": "https://github.com/tester/repo/issues/12#issuecomment-1201",
                        "user": {"login": "tester"},
                        "reactions": {"total_count": 2, "+1": 1, "heart": 1},
                    }
                ],
            }
        ],
        pr_review_threads=[
            {
                "thread_id": "tester/repo#7:9001",
                "repo": "tester/repo",
                "pr_number": 7,
                "path": "src/app.py",
                "line": 18,
                "comments": [
                    {
                        "id": 9001,
                        "body": "Please tighten this check.",
                        "created_at": "2026-04-01T00:00:00Z",
                        "html_url": "https://github.com/tester/repo/pull/7#discussion_r9001",
                        "user": {"login": "tester"},
                        "reactions": {"total_count": 1, "+1": 1},
                    }
                ],
            }
        ],
        pull_request_reviews=[
            {
                "id": 501,
                "repo": "tester/repo",
                "pr_number": 7,
                "state": "APPROVED",
                "created_at": "2026-04-01T00:05:00Z",
                "user": {"login": "tester"},
                "reactions": {"total_count": 3, "+1": 2, "heart": 1},
            }
        ],
        reviews_authored=[
            {
                "owner": "tester",
                "repo": "repo",
                "pr_number": 7,
                "review_id": "r7",
                "state": "APPROVED",
                "body": "LGTM",
                "submitted_at": "2026-04-01T00:06:00Z",
                "comments": [],
                "reactions": {"total_count": 4, "+1": 3, "heart": 1},
            }
        ],
    )

    with patch("app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=fake_data)):
        items = [item async for item in source.fetch_items("tester", "mini-1", None)]

    discussion_items = [item for item in items if item.item_type == "discussion"]
    assert len(discussion_items) == 2
    assert any(item.metadata.get("discussion_kind") == "issue_thread" for item in discussion_items)
    assert any(item.metadata.get("discussion_kind") == "pr_review_thread" for item in discussion_items)

    pr_review_item = next(item for item in items if item.item_type == "pr_review")
    assert pr_review_item.metadata["reactions"]["total_count"] == 3
    assert pr_review_item.metadata["positive_reactions_count"] == 3

    review_authored_item = next(item for item in items if item.item_type == "review_authored")
    assert review_authored_item.metadata["reactions"]["total_count"] == 4
    assert review_authored_item.metadata["positive_reactions_count"] == 4
