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
