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
            context="commit_message",
        )
        assert item.external_id == "commit:abc123"
        assert item.source_type == "github"
        assert item.item_type == "commit"
        assert item.content == "some content"
        assert item.context == "commit_message"

    def test_defaults(self):
        item = EvidenceItem(
            external_id="x",
            source_type="github",
            item_type="commit",
            content="c",
        )
        assert item.context == "general"
        assert item.source_uri is None
        assert item.author_id is None
        assert item.audience_id is None
        assert item.scope is None
        assert item.raw_body is None
        assert item.raw_body_ref is None
        assert item.raw_context is None
        assert item.provenance is None
        assert item.metadata is None
        assert item.privacy == "public"

    def test_review_grade_envelope_fields(self):
        item = EvidenceItem(
            external_id="review:pr-1#comment-2",
            source_type="github",
            item_type="review",
            content="Comment:\nPlease add the retry test.",
            context="code_review",
            source_uri="https://github.com/acme/app/pull/1#discussion_r2",
            author_id="github:reviewer",
            audience_id="github:author",
            target_id="github:author",
            scope={"type": "repo", "id": "acme/app", "path": "tests/test_retry.py"},
            raw_body="Please add the retry test.",
            raw_body_ref="github:discussion_r2",
            raw_context={"ref": "github:pull/1/thread/2", "hunk": "@@ -1 +1 @@"},
            provenance={"collector": "github", "confidence": 1.0},
        )

        assert item.source_uri == "https://github.com/acme/app/pull/1#discussion_r2"
        assert item.author_id == "github:reviewer"
        assert item.audience_id == "github:author"
        assert item.scope == {"type": "repo", "id": "acme/app", "path": "tests/test_retry.py"}
        assert item.raw_body == "Please add the retry test."
        assert item.raw_body_ref == "github:discussion_r2"
        assert item.raw_context == {"ref": "github:pull/1/thread/2", "hunk": "@@ -1 +1 @@"}
        assert item.provenance == {"collector": "github", "confidence": 1.0}

    def test_private_privacy(self):
        item = EvidenceItem(
            external_id="session:abc#0",
            source_type="claude_code",
            item_type="session",
            content="hey",
            context="private_chat",
            privacy="private",
        )
        assert item.context == "private_chat"
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
            "pull_request_url": "https://api.github.com/repos/testuser/myrepo/pulls/42",
            "body": "LGTM",
            "path": "src/main.py",
            "diff_hunk": "@@ -1,5 +1,5 @@",
            "line": 12,
            "side": "RIGHT",
            "html_url": "https://github.com/testuser/myrepo/pull/42#discussion_r999",
            "user": {"login": "testuser"},
        }
    ],
    "pull_request_reviews": [
        {
            "id": 100,
            "state": "APPROVED",
            "body": "LGTM after the test update.",
            "submitted_at": "2026-04-01T12:30:00Z",
            "commit_id": "deadbeef1234",
            "html_url": "https://github.com/testuser/myrepo/pull/42#pullrequestreview-100",
            "repo": "testuser/myrepo",
            "pr_number": 42,
            "pr_node_id": "PR_node",
            "pr_html_url": "https://github.com/testuser/myrepo/pull/42",
            "user": {"login": "testuser"},
        }
    ],
    "issue_comments": [
        {
            "id": 777,
            "body": "Thanks for the report!",
            "html_url": "https://github.com/testuser/myrepo/issues/5",
            "user": {"login": "testuser"},
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
        pull_request_reviews=_FAKE_GITHUB_DATA["pull_request_reviews"],
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
    async def test_emits_pr_review_state_events_with_temporal_context(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        review_items = [i for i in items if i.item_type == "pr_review"]
        assert len(review_items) == 1
        review = review_items[0]
        assert review.external_id == "pr_review:testuser/myrepo#42:100"
        assert review.context == "code_review"
        assert review.source_uri == "https://github.com/testuser/myrepo/pull/42#pullrequestreview-100"
        assert review.author_id == "testuser"
        assert review.target_id == "github:testuser/myrepo#42"
        assert review.scope == {"type": "repo", "id": "testuser/myrepo", "pr_number": 42}
        assert review.raw_body == "LGTM after the test update."
        assert review.raw_body_ref == "github:pull_request_review:100"
        assert review.raw_context["state"] == "APPROVED"
        assert review.raw_context["submitted_at"] == "2026-04-01T12:30:00Z"
        assert review.provenance["review_state_event"] is True
        assert review.provenance["authored_by_subject"] is True
        assert review.metadata["state"] == "APPROVED"
        assert "State: APPROVED" in review.content

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
    async def test_emits_commit_diffs_with_envelope_and_file_metadata(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()
        fake_data.commit_diffs = [
            {
                "sha": "deadbeef1234",
                "repo": "testuser/myrepo",
                "html_url": "https://github.com/testuser/myrepo/commit/deadbeef1234",
                "author": {"login": "testuser"},
                "commit": {
                    "message": "fix: correct off-by-one error",
                    "author": {"date": "2026-04-01T12:00:00Z"},
                },
                "stats": {"additions": 3, "deletions": 1, "total": 4},
                "files": [
                    {
                        "filename": "src/main.py",
                        "status": "modified",
                        "additions": 3,
                        "deletions": 1,
                        "changes": 4,
                        "patch": "@@ -1 +1 @@\n-old\n+new",
                    }
                ],
            }
        ]

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        diff_items = [i for i in items if i.item_type == "commit_diff"]
        assert len(diff_items) == 1
        assert diff_items[0].external_id == "commit_diff:deadbeef1234"
        assert diff_items[0].context == "code_change"
        assert diff_items[0].source_uri == "https://github.com/testuser/myrepo/commit/deadbeef1234"
        assert diff_items[0].author_id == "testuser"
        assert diff_items[0].scope == {
            "type": "repo",
            "id": "testuser/myrepo",
            "commit": "deadbeef1234",
        }
        assert diff_items[0].raw_body == "fix: correct off-by-one error"
        assert diff_items[0].provenance["authored_by_subject"] is True
        assert diff_items[0].metadata["files"][0]["filename"] == "src/main.py"
        assert "Patch:" in diff_items[0].content

    @pytest.mark.asyncio
    async def test_emits_pr_review_threads_with_target_context(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()
        fake_data.pr_review_threads = [
            {
                "thread_id": "testuser/myrepo#42:999",
                "repo": "testuser/myrepo",
                "pr_number": 42,
                "pr_node_id": "PR_node",
                "path": "src/main.py",
                "line": 12,
                "side": "RIGHT",
                "diff_hunk": "@@ -10,2 +10,2 @@",
                "comments": [
                    {
                        "id": 999,
                        "body": "This needs a test.",
                        "created_at": "2026-04-01T12:00:00Z",
                        "html_url": "https://github.com/testuser/myrepo/pull/42#discussion_r999",
                        "user": {"login": "reviewer"},
                    },
                    {
                        "id": 1000,
                        "body": "Added one.",
                        "created_at": "2026-04-01T12:10:00Z",
                        "in_reply_to_id": 999,
                        "html_url": "https://github.com/testuser/myrepo/pull/42#discussion_r1000",
                        "user": {"login": "testuser"},
                    },
                ],
            }
        ]

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        thread_items = [i for i in items if i.item_type == "pr_review_thread"]
        assert len(thread_items) == 1
        assert thread_items[0].external_id == "pr_review_thread:testuser/myrepo#42:999@1000"
        assert thread_items[0].context == "code_review"
        assert thread_items[0].source_uri.endswith("discussion_r999")
        assert thread_items[0].target_id == "github:testuser/myrepo#42:src/main.py:12"
        assert thread_items[0].scope == {
            "type": "repo",
            "id": "testuser/myrepo",
            "pr_number": 42,
            "path": "src/main.py",
            "line": 12,
            "side": "RIGHT",
        }
        assert thread_items[0].provenance["authored_by_subject"] is True
        assert thread_items[0].metadata["authors"] == ["reviewer", "testuser"]

    @pytest.mark.asyncio
    async def test_emits_issue_threads_with_pr_relationship(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()
        fake_data.issue_threads = [
            {
                "repo": "testuser/myrepo",
                "pr_number": 42,
                "pr_node_id": "PR_node",
                "html_url": "https://github.com/testuser/myrepo/pull/42",
                "comments": [
                    {
                        "id": 777,
                        "body": "Can you explain the rollout plan?",
                        "created_at": "2026-04-01T12:00:00Z",
                        "html_url": "https://github.com/testuser/myrepo/pull/42#issuecomment-777",
                        "user": {"login": "reviewer"},
                    },
                    {
                        "id": 778,
                        "body": "Yes, this ships behind a flag.",
                        "created_at": "2026-04-01T12:10:00Z",
                        "html_url": "https://github.com/testuser/myrepo/pull/42#issuecomment-778",
                        "user": {"login": "testuser"},
                    },
                ],
            }
        ]

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        thread_items = [i for i in items if i.item_type == "issue_thread"]
        assert len(thread_items) == 1
        assert thread_items[0].external_id == "issue_thread:testuser/myrepo#42@778"
        assert thread_items[0].context == "issue_discussion"
        assert thread_items[0].source_uri == "https://github.com/testuser/myrepo/pull/42"
        assert thread_items[0].scope == {
            "type": "repo",
            "id": "testuser/myrepo",
            "pr_number": 42,
        }
        assert thread_items[0].provenance["authored_comment_ids"] == [778]
        assert thread_items[0].metadata["comment_ids"] == [777, 778]
        assert thread_items[0].metadata["authors"] == ["reviewer", "testuser"]

    @pytest.mark.asyncio
    async def test_enriches_review_comment_provenance(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        review = next(i for i in items if i.item_type == "review")
        assert review.author_id == "testuser"
        assert review.source_uri == "https://github.com/testuser/myrepo/pull/42#discussion_r999"
        assert review.target_id == "github:testuser/myrepo#42:src/main.py:12"
        assert review.scope == {
            "type": "repo",
            "id": "testuser/myrepo",
            "pr_number": 42,
            "path": "src/main.py",
            "line": 12,
            "side": "RIGHT",
        }
        assert review.raw_body == "LGTM"
        assert review.raw_body_ref == "github:pull_request_review_comment:999"
        assert review.raw_context["diff_hunk"] == "@@ -1,5 +1,5 @@"
        assert review.provenance["authored_by_subject"] is True
        assert review.metadata["repo"] == "testuser/myrepo"
        assert review.metadata["pr_number"] == 42

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
    async def test_emits_expected_contexts_by_item_type(self):
        source = GitHubSource()
        fake_data = _make_fake_github_data()

        with patch.object(source, "_fetch_with_cache", new=AsyncMock(return_value=fake_data)):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", MagicMock()):
                items.append(item)

        contexts_by_type = {item.item_type: item.context for item in items}
        assert contexts_by_type["commit"] == "commit_message"
        assert contexts_by_type["pr"] == "issue_discussion"
        assert contexts_by_type["pr_review"] == "code_review"
        assert contexts_by_type["review"] == "code_review"
        assert contexts_by_type["issue_comment"] == "issue_discussion"

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
                "pr_review:testuser/myrepo#42:100",
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
        assert all(item.context == "private_chat" for item in items)

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
        assert all(item.context == "private_chat" for item in items)

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
