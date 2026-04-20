"""Tests for the EvidenceItem dataclass + IngestionSource.fetch_items() interface.

Covers:
- EvidenceItem field shapes
- GitHubSource.fetch_items() emits items with expected external_id prefixes
- ClaudeCodeSource.fetch_items() marks items as private
- since_external_ids filter skips already-seen items
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.plugins.base import EvidenceItem
from app.plugins.sources.claude_code import ClaudeCodeSource
from app.plugins.sources.github import GitHubSource


# ---------------------------------------------------------------------------
# EvidenceItem dataclass
# ---------------------------------------------------------------------------


class TestEvidenceItemDataclass:
    def test_required_fields(self):
        item = EvidenceItem(
            external_id="commit:abc123",
            source_type="github",
            item_type="commit",
            content="some content",
        )
        assert item.external_id == "commit:abc123"
        assert item.source_type == "github"
        assert item.item_type == "commit"
        assert item.content == "some content"

    def test_defaults(self):
        item = EvidenceItem(
            external_id="x",
            source_type="github",
            item_type="commit",
            content="c",
        )
        assert item.metadata is None
        assert item.privacy == "public"

    def test_private_privacy(self):
        item = EvidenceItem(
            external_id="session:abc#0",
            source_type="claude_code",
            item_type="session",
            content="hey",
            privacy="private",
        )
        assert item.privacy == "private"


# ---------------------------------------------------------------------------
# GitHubSource.fetch_items()
# ---------------------------------------------------------------------------

_FAKE_GITHUB_DATA = {
    "profile": {"login": "testuser", "name": "Test User"},
    "repos": [],
    "commits": [
        {
            "sha": "deadbeef1234",
            "commit": {
                "message": "fix: correct off-by-one error",
                "author": {"name": "Test User"},
            },
            "repository": {"full_name": "testuser/myrepo"},
        },
        {
            "sha": "cafebabe5678",
            "commit": {
                "message": "feat: add new widget",
                "author": {"name": "Test User"},
            },
            "repository": {"full_name": "testuser/myrepo"},
        },
    ],
    "pull_requests": [
        {
            "number": 42,
            "title": "Improve performance",
            "body": "This speeds things up.",
            "state": "merged",
            "base": {"repo": {"full_name": "testuser/myrepo"}},
        }
    ],
    "review_comments": [
        {
            "id": 999,
            "pull_request_review_id": 100,
            "body": "LGTM",
            "path": "src/main.py",
            "diff_hunk": "@@ -1,5 +1,5 @@",
        }
    ],
    "issue_comments": [
        {
            "id": 777,
            "body": "Thanks for the report!",
            "html_url": "https://github.com/testuser/myrepo/issues/5",
        }
    ],
    "repo_languages": {},
    "commit_diffs": [],
    "pr_review_threads": [],
    "issue_threads": [],
}


def _make_fake_github_data():
    from app.ingestion.github import GitHubData

    return GitHubData(
        profile=_FAKE_GITHUB_DATA["profile"],
        repos=_FAKE_GITHUB_DATA["repos"],
        commits=_FAKE_GITHUB_DATA["commits"],
        pull_requests=_FAKE_GITHUB_DATA["pull_requests"],
        review_comments=_FAKE_GITHUB_DATA["review_comments"],
        issue_comments=_FAKE_GITHUB_DATA["issue_comments"],
        repo_languages=_FAKE_GITHUB_DATA["repo_languages"],
        commit_diffs=_FAKE_GITHUB_DATA["commit_diffs"],
        pr_review_threads=_FAKE_GITHUB_DATA["pr_review_threads"],
        issue_threads=_FAKE_GITHUB_DATA["issue_threads"],
    )


class TestGitHubSourceFetchItems:
    @pytest.mark.asyncio
    async def test_emits_commits_with_correct_external_id(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        commit_items = [i for i in items if i.item_type == "commit"]
        assert len(commit_items) == 2
        external_ids = {i.external_id for i in commit_items}
        assert "commit:deadbeef1234" in external_ids
        assert "commit:cafebabe5678" in external_ids

    @pytest.mark.asyncio
    async def test_emits_prs_with_correct_external_id(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        pr_items = [i for i in items if i.item_type == "pr"]
        assert len(pr_items) == 1
        assert pr_items[0].external_id == "pr:testuser/myrepo#42"

    @pytest.mark.asyncio
    async def test_emits_reviews_with_correct_external_id(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        review_items = [i for i in items if i.item_type == "review"]
        assert len(review_items) == 1
        assert review_items[0].external_id == "review:100#999"

    @pytest.mark.asyncio
    async def test_emits_issue_comments_with_correct_external_id(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        comment_items = [i for i in items if i.item_type == "issue_comment"]
        assert len(comment_items) == 1
        assert comment_items[0].external_id == "issue_comment:777"

    @pytest.mark.asyncio
    async def test_all_items_are_public(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        assert all(item.privacy == "public" for item in items)

    @pytest.mark.asyncio
    async def test_since_filter_skips_known_commits(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            since = {"commit:deadbeef1234"}
            items = []
            async for item in source.fetch_items(
                "testuser", "mini-1", MagicMock(), since_external_ids=since
            ):
                items.append(item)

        commit_items = [i for i in items if i.item_type == "commit"]
        # Only the second commit should be included
        assert len(commit_items) == 1
        assert commit_items[0].external_id == "commit:cafebabe5678"

    @pytest.mark.asyncio
    async def test_since_filter_skips_all_items(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            since = {
                "commit:deadbeef1234",
                "commit:cafebabe5678",
                "pr:testuser/myrepo#42",
                "review:100#999",
                "issue_comment:777",
            }
            items = []
            async for item in source.fetch_items(
                "testuser", "mini-1", MagicMock(), since_external_ids=since
            ):
                items.append(item)

        assert items == []

    @pytest.mark.asyncio
    async def test_falls_back_to_fetch_github_data_when_no_session(self):
        """When session is None, fetch_items uses fetch_github_data() directly."""
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch(
            "app.plugins.sources.github.fetch_github_data", new=AsyncMock(return_value=fake_data)
        ):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", None):
                items.append(item)

        assert len(items) > 0


# ---------------------------------------------------------------------------
# ClaudeCodeSource.fetch_items()
# ---------------------------------------------------------------------------


def _make_jsonl_file(tmp_dir: Path, session_uuid: str, messages: list[str]) -> Path:
    """Create a fake Claude Code JSONL file with the given user messages."""
    filepath = tmp_dir / f"{session_uuid}.jsonl"
    lines = []
    for i, msg in enumerate(messages):
        entry = {
            "type": "user",
            "timestamp": f"2026-01-0{i + 1}T12:00:00Z",
            "cwd": "/home/user/project",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": msg}],
            },
        }
        lines.append(json.dumps(entry))
    filepath.write_text("\n".join(lines))
    return filepath


class TestClaudeCodeSourceFetchItems:
    @pytest.mark.asyncio
    async def test_emits_session_items_with_correct_external_id(self):
        source = ClaudeCodeSource()
        session_uuid = str(uuid.uuid4())

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _make_jsonl_file(
                tmp_dir, session_uuid, ["I prefer Python over JS", "Let's use FastAPI"]
            )

            items = []
            async for item in source.fetch_items(str(tmp_dir), "mini-1", None):
                items.append(item)

        assert len(items) == 2
        assert items[0].external_id == f"session:{session_uuid}#0"
        assert items[1].external_id == f"session:{session_uuid}#1"

    @pytest.mark.asyncio
    async def test_all_items_are_private(self):
        source = ClaudeCodeSource()
        session_uuid = str(uuid.uuid4())

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _make_jsonl_file(tmp_dir, session_uuid, ["I think we should refactor this"])

            items = []
            async for item in source.fetch_items(str(tmp_dir), "mini-1", None):
                items.append(item)

        assert len(items) >= 1
        assert all(item.privacy == "private" for item in items)

    @pytest.mark.asyncio
    async def test_source_type_is_claude_code(self):
        source = ClaudeCodeSource()
        session_uuid = str(uuid.uuid4())

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _make_jsonl_file(tmp_dir, session_uuid, ["I like clean architecture"])

            items = []
            async for item in source.fetch_items(str(tmp_dir), "mini-1", None):
                items.append(item)

        assert all(item.source_type == "claude_code" for item in items)
        assert all(item.item_type == "session" for item in items)

    @pytest.mark.asyncio
    async def test_since_filter_skips_known_turns(self):
        source = ClaudeCodeSource()
        session_uuid = str(uuid.uuid4())

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _make_jsonl_file(
                tmp_dir,
                session_uuid,
                [
                    "I prefer strongly-typed languages",
                    "Let's use dependency injection here",
                ],
            )

            # Mark turn 0 as already seen
            since = {f"session:{session_uuid}#0"}
            items = []
            async for item in source.fetch_items(
                str(tmp_dir), "mini-1", None, since_external_ids=since
            ):
                items.append(item)

        assert len(items) == 1
        assert items[0].external_id == f"session:{session_uuid}#1"

    @pytest.mark.asyncio
    async def test_nonexistent_path_yields_nothing(self):
        source = ClaudeCodeSource()
        items = []
        async for item in source.fetch_items("/tmp/does_not_exist_xyzzy", "mini-1", None):
            items.append(item)
        assert items == []
