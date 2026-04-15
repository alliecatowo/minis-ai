"""Tests for plugin ingestion sources.

Covers:
- Class structure (IngestionSource ABC, name, description)
- Formatting functions with mock data
- Error handling with empty/missing data
- No real HTTP calls — all external I/O is mocked
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.plugins.base import IngestionResult, IngestionSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_github_data(**kwargs):
    """Create a minimal GitHubData for testing.

    Also attaches commit_diffs, pr_review_threads, issue_threads as plain
    attributes to simulate the extended data that the GitHubSource plugin
    accesses (these may or may not be dataclass fields depending on the version).
    """
    from app.ingestion.github import GitHubData
    import dataclasses

    # Determine which fields exist on the dataclass
    field_names = {f.name for f in dataclasses.fields(GitHubData)}

    base_defaults = {
        "profile": {
            "name": "Ada Lovelace",
            "login": "ada",
            "bio": "First programmer",
            "company": "Babbage & Co",
            "location": "London",
            "public_repos": 5,
            "followers": 100,
        },
        "repos": [
            {
                "full_name": "ada/engine",
                "name": "engine",
                "description": "Analytical engine",
                "language": "Python",
                "stargazers_count": 42,
                "topics": ["math", "engine"],
            }
        ],
        "commits": [
            {
                "commit": {"message": "Add carry mechanism"},
                "repository": {"full_name": "ada/engine"},
            }
        ],
        "pull_requests": [
            {
                "title": "Improve loop notation",
                "body": "This PR improves loop handling by refactoring the notation module.",
                "repository_url": "https://api.github.com/repos/ada/engine",
            }
        ],
        "review_comments": [
            {"body": "I disagree with this approach, we should use recursion.", "path": "engine.py", "diff_hunk": ""},
            {"body": "LGTM", "path": "README.md", "diff_hunk": ""},
        ],
        "issue_comments": [
            {"body": "This is a known issue, however, there is a workaround.", "html_url": "https://github.com/ada/engine/issues/1"}
        ],
        "repo_languages": {
            "ada/engine": {"Python": 50000, "C": 10000}
        },
        # Extended fields (may be added as proper dataclass fields in later versions)
        "commit_diffs": [],
        "pr_review_threads": [],
        "issue_threads": [],
    }
    base_defaults.update(kwargs)

    # Split kwargs into dataclass fields and extra attributes
    dc_kwargs = {k: v for k, v in base_defaults.items() if k in field_names}
    extra_attrs = {k: v for k, v in base_defaults.items() if k not in field_names}

    obj = GitHubData(**dc_kwargs)

    # Attach any extra attributes that the plugin code accesses dynamically
    for attr, val in extra_attrs.items():
        setattr(obj, attr, val)

    return obj


# ---------------------------------------------------------------------------
# GitHub Source
# ---------------------------------------------------------------------------


class TestGitHubSource:
    def test_implements_ingestion_source(self):
        from app.plugins.sources.github import GitHubSource

        source = GitHubSource()
        assert isinstance(source, IngestionSource)

    def test_name(self):
        from app.plugins.sources.github import GitHubSource

        assert GitHubSource.name == "github"
        assert GitHubSource().name == "github"

    @pytest.mark.asyncio
    async def test_fetch_returns_ingestion_result(self):
        from app.plugins.sources.github import GitHubSource

        github_data = make_github_data()
        with patch("app.plugins.sources.github.fetch_github_data", AsyncMock(return_value=github_data)):
            source = GitHubSource()
            result = await source.fetch("ada")

        assert isinstance(result, IngestionResult)
        assert result.source_name == "github"
        assert result.identifier == "ada"
        assert len(result.evidence) > 0

    @pytest.mark.asyncio
    async def test_fetch_stats(self):
        from app.plugins.sources.github import GitHubSource

        github_data = make_github_data()
        with patch("app.plugins.sources.github.fetch_github_data", AsyncMock(return_value=github_data)):
            result = await GitHubSource().fetch("ada")

        assert result.stats["repos_count"] == 1
        assert result.stats["commits_analyzed"] == 1
        assert result.stats["prs_analyzed"] == 1

    @pytest.mark.asyncio
    async def test_fetch_raw_data_structure(self):
        from app.plugins.sources.github import GitHubSource

        github_data = make_github_data()
        with patch("app.plugins.sources.github.fetch_github_data", AsyncMock(return_value=github_data)):
            result = await GitHubSource().fetch("ada")

        assert "profile" in result.raw_data
        assert "repos_summary" in result.raw_data
        assert "pull_requests_full" in result.raw_data
        assert "commits_full" in result.raw_data

    @pytest.mark.asyncio
    async def test_fetch_with_empty_data(self):
        from app.plugins.sources.github import GitHubSource

        github_data = make_github_data(
            profile={},
            repos=[],
            commits=[],
            pull_requests=[],
            review_comments=[],
            issue_comments=[],
            repo_languages={},
        )
        with patch("app.plugins.sources.github.fetch_github_data", AsyncMock(return_value=github_data)):
            result = await GitHubSource().fetch("nobody")

        assert isinstance(result, IngestionResult)
        assert result.stats["repos_count"] == 0

    def test_aggregate_languages(self):
        from app.plugins.sources.github import _aggregate_languages

        github_data = make_github_data(
            repo_languages={
                "user/a": {"Python": 5000, "JavaScript": 2000},
                "user/b": {"Python": 3000, "Rust": 1000},
            }
        )
        langs = _aggregate_languages(github_data)
        assert langs["Python"] == 8000
        assert langs["JavaScript"] == 2000
        assert langs["Rust"] == 1000
        # Sorted descending
        keys = list(langs.keys())
        assert keys[0] == "Python"

    def test_aggregate_languages_empty(self):
        from app.plugins.sources.github import _aggregate_languages

        github_data = make_github_data(repo_languages={})
        assert _aggregate_languages(github_data) == {}

    def test_aggregate_primary_languages(self):
        from app.plugins.sources.github import _aggregate_primary_languages

        github_data = make_github_data(
            repos=[
                {"language": "Python"},
                {"language": "Python"},
                {"language": "Rust"},
                {"language": None},
            ]
        )
        result = _aggregate_primary_languages(github_data)
        assert result["Python"] == 2
        assert result["Rust"] == 1
        assert None not in result

    def test_aggregate_primary_languages_empty(self):
        from app.plugins.sources.github import _aggregate_primary_languages

        github_data = make_github_data(repos=[])
        assert _aggregate_primary_languages(github_data) == {}


# ---------------------------------------------------------------------------
# HackerNews Source
# ---------------------------------------------------------------------------


class TestHackerNewsSource:
    def test_implements_ingestion_source(self):
        from app.plugins.sources.hackernews import HackerNewsSource

        assert isinstance(HackerNewsSource(), IngestionSource)

    def test_name(self):
        from app.plugins.sources.hackernews import HackerNewsSource

        assert HackerNewsSource.name == "hackernews"

    @pytest.mark.asyncio
    async def test_fetch_returns_ingestion_result(self):
        from app.plugins.sources.hackernews import HackerNewsSource

        comments = [
            {"comment_text": "I disagree with this approach.", "story_title": "Debate", "points": 5},
        ]
        stories = [
            {"title": "My project", "points": 100, "num_comments": 20, "url": "https://example.com"},
        ]

        with patch("app.plugins.sources.hackernews._fetch_hn_data", AsyncMock(return_value=(comments, stories))):
            result = await HackerNewsSource().fetch("ada_hn")

        assert isinstance(result, IngestionResult)
        assert result.source_name == "hackernews"
        assert result.identifier == "ada_hn"
        assert len(result.evidence) > 0

    @pytest.mark.asyncio
    async def test_fetch_empty_data(self):
        from app.plugins.sources.hackernews import HackerNewsSource

        with patch("app.plugins.sources.hackernews._fetch_hn_data", AsyncMock(return_value=([], []))):
            result = await HackerNewsSource().fetch("nobody")

        assert isinstance(result, IngestionResult)
        assert result.stats["comments_fetched"] == 0
        assert result.stats["stories_fetched"] == 0
        assert "No public HackerNews activity" in result.evidence

    def test_format_stories(self):
        from app.plugins.sources.hackernews import _format_stories

        stories = [
            {"title": "Great Talk", "points": 200, "num_comments": 50, "url": "https://news.ycombinator.com/item?id=1"},
            {"title": "Another Post", "points": 50, "num_comments": 5, "url": ""},
        ]
        result = _format_stories(stories)
        assert "Great Talk" in result
        assert "200 points" in result
        assert "Another Post" in result
        assert "### Submitted Stories" in result

    def test_format_stories_extracts_domain(self):
        from app.plugins.sources.hackernews import _format_stories

        stories = [{"title": "Cool", "points": 10, "num_comments": 0, "url": "https://example.com/article"}]
        result = _format_stories(stories)
        assert "example.com" in result

    def test_format_comments(self):
        from app.plugins.sources.hackernews import _format_comments

        comments = [
            {
                "comment_text": "I think this is wrong, we should reconsider.",
                "story_title": "Some Discussion",
                "points": 10,
            }
        ]
        result = _format_comments(comments, header="Test Header", preamble="Test preamble")
        assert "### Test Header" in result
        assert "Some Discussion" in result
        assert "reconsider" in result

    def test_format_comments_strips_html(self):
        from app.plugins.sources.hackernews import _format_comments

        comments = [
            {"comment_text": "<p>Hello <b>world</b></p>", "story_title": "Discussion", "points": 0}
        ]
        result = _format_comments(comments, header="H", preamble="P")
        assert "<p>" not in result
        assert "<b>" not in result
        assert "Hello" in result
        assert "world" in result

    def test_format_comments_truncates_long_text(self):
        from app.plugins.sources.hackernews import _format_comments

        long_text = "X" * 1000
        comments = [{"comment_text": long_text, "story_title": "Test", "points": 0}]
        result = _format_comments(comments, header="H", preamble="P")
        assert "..." in result

    def test_format_hn_evidence_with_conflict_comments(self):
        from app.plugins.sources.hackernews import _format_hn_evidence

        conflict_comments = [
            {"comment_text": "I disagree with this.", "story_title": "Debate", "points": 5}
        ]
        result = _format_hn_evidence("user", conflict_comments, [])
        assert "CONFLICT" in result or "OPINION" in result

    def test_format_hn_evidence_empty(self):
        from app.plugins.sources.hackernews import _format_hn_evidence

        result = _format_hn_evidence("ghost", [], [])
        assert "No public HackerNews activity" in result
        assert "ghost" in result

    def test_strip_html(self):
        from app.plugins.sources.hackernews import _strip_html

        html = "<p>Hello &amp; <b>world</b></p>"
        result = _strip_html(html)
        assert "<p>" not in result
        assert "<b>" not in result
        assert "&amp;" not in result
        assert "Hello" in result
        assert "world" in result

    def test_partition_comments(self):
        from app.plugins.sources.hackernews import _partition_comments

        comments = [
            {"comment_text": "I disagree with this."},
            {"comment_text": "Interesting post!"},
            {"comment_text": "Actually, that's wrong."},
            {"comment_text": ""},  # empty — should be skipped
        ]
        conflict, routine = _partition_comments(comments)
        assert len(conflict) == 2
        assert len(routine) == 1


# ---------------------------------------------------------------------------
# StackOverflow Source
# ---------------------------------------------------------------------------


class TestStackOverflowSource:
    def test_implements_ingestion_source(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        assert isinstance(StackOverflowSource(), IngestionSource)

    def test_name(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        assert StackOverflowSource.name == "stackoverflow"

    def test_format_evidence_basic(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()
        answers = [
            {
                "_question_title": "How to use Python decorators?",
                "tags": ["python", "decorators"],
                "score": 250,
                "is_accepted": True,
                "body": "<p>Decorators are functions that modify other functions.</p>",
            }
        ]
        user_info = {"display_name": "Ada", "reputation": 9999}
        result = source._format_evidence(answers, user_info)

        assert "## Stack Overflow Answers" in result
        assert "Ada" in result
        assert "9,999" in result
        assert "Python decorators" in result
        assert "Score: 250" in result
        assert "Accepted" in result
        assert "Decorators are functions" in result

    def test_format_evidence_empty_answers(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()
        result = source._format_evidence([], {"display_name": "Nobody", "reputation": 0})
        assert "## Stack Overflow Answers" in result
        assert "Nobody" in result

    def test_format_evidence_truncates_long_body(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()
        long_body = "<p>" + "A" * 2000 + "</p>"
        answers = [
            {
                "_question_title": "Long answer",
                "tags": [],
                "score": 5,
                "is_accepted": False,
                "body": long_body,
            }
        ]
        result = source._format_evidence(answers, {"display_name": "Dev", "reputation": 100})
        assert "..." in result

    def test_format_evidence_tags_summary(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()
        answers = [
            {"_question_title": "Q1", "tags": ["python", "django"], "score": 10, "is_accepted": False, "body": "Answer 1"},
            {"_question_title": "Q2", "tags": ["python", "flask"], "score": 5, "is_accepted": False, "body": "Answer 2"},
        ]
        result = source._format_evidence(answers, {"display_name": "Dev", "reputation": 500})
        assert "python (2)" in result
        assert "Top tags" in result

    @pytest.mark.asyncio
    async def test_resolve_user_id_numeric(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()
        client = MagicMock()
        user_id = await source._resolve_user_id(client, "12345")
        assert user_id == 12345
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_user_id_by_name(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "items": [{"display_name": "Ada", "user_id": 99}]
        }
        mock_resp.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=mock_resp)

        user_id = await source._resolve_user_id(client, "Ada")
        assert user_id == 99

    @pytest.mark.asyncio
    async def test_resolve_user_id_not_found(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"items": []}
        mock_resp.raise_for_status = MagicMock()
        client = MagicMock()
        client.get = AsyncMock(return_value=mock_resp)

        with pytest.raises(ValueError, match="No Stack Overflow user found"):
            await source._resolve_user_id(client, "unknown_user_xyz")

    def test_strip_html(self):
        from app.plugins.sources.stackoverflow import _strip_html

        result = _strip_html("<p>Hello &amp; <code>world</code></p>")
        assert "<p>" not in result
        assert "&amp;" not in result
        assert "Hello" in result
        assert "world" in result


# ---------------------------------------------------------------------------
# Blog Source
# ---------------------------------------------------------------------------


class TestBlogSource:
    def test_implements_ingestion_source(self):
        from app.plugins.sources.blog import BlogSource

        assert isinstance(BlogSource(), IngestionSource)

    def test_name(self):
        from app.plugins.sources.blog import BlogSource

        assert BlogSource.name == "blog"

    @pytest.mark.asyncio
    async def test_fetch_no_feed_found(self):
        from app.plugins.sources.blog import BlogSource

        with patch("app.plugins.sources.blog._resolve_feed", AsyncMock(return_value=("http://example.com", None))):
            result = await BlogSource().fetch("http://example.com")

        assert isinstance(result, IngestionResult)
        assert result.evidence == ""
        assert result.stats["post_count"] == 0
        assert "error" in result.raw_data

    @pytest.mark.asyncio
    async def test_fetch_rss_feed(self):
        from app.plugins.sources.blog import BlogSource

        rss_xml = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Blog</title>
    <item>
      <title>My First Post</title>
      <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>
      <description>I think this is a great way to write code.</description>
      <category>Python</category>
    </item>
  </channel>
</rss>"""
        with patch("app.plugins.sources.blog._resolve_feed", AsyncMock(return_value=("http://example.com/feed", rss_xml))):
            result = await BlogSource().fetch("http://example.com")

        assert isinstance(result, IngestionResult)
        assert result.stats["post_count"] == 1
        assert "My First Post" in result.evidence

    def test_looks_like_feed_xml(self):
        from app.plugins.sources.blog import _looks_like_feed

        assert _looks_like_feed("<?xml version='1.0'?><rss>")
        assert _looks_like_feed("<feed xmlns='http://www.w3.org/2005/Atom'>")
        assert _looks_like_feed("<channel>")

    def test_looks_like_feed_html(self):
        from app.plugins.sources.blog import _looks_like_feed

        assert not _looks_like_feed("<!DOCTYPE html><html><body>")
        assert not _looks_like_feed("<html>")

    def test_parse_rss_feed(self):
        from app.plugins.sources.blog import _parse_feed

        rss_xml = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Post One</title>
      <pubDate>2024-01-15T00:00:00Z</pubDate>
      <description>Content of the first post.</description>
      <category>Python</category>
    </item>
    <item>
      <title>Post Two</title>
      <pubDate>2024-02-20T00:00:00Z</pubDate>
      <description>Content of the second post.</description>
    </item>
  </channel>
</rss>"""
        posts = _parse_feed(rss_xml)
        assert len(posts) == 2
        titles = [p["title"] for p in posts]
        assert "Post One" in titles
        assert "Post Two" in titles

    def test_parse_atom_feed(self):
        from app.plugins.sources.blog import _parse_feed

        atom_xml = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Atom Entry</title>
    <updated>2024-03-01T12:00:00Z</updated>
    <summary>Summary text here.</summary>
    <category term="Rust"/>
  </entry>
</feed>"""
        posts = _parse_feed(atom_xml)
        assert len(posts) == 1
        assert posts[0]["title"] == "Atom Entry"
        assert "Rust" in posts[0]["tags"]

    def test_parse_invalid_xml(self):
        from app.plugins.sources.blog import _parse_feed

        posts = _parse_feed("not valid xml at all {{{{")
        assert posts == []

    def test_format_evidence(self):
        from app.plugins.sources.blog import _format_evidence

        posts = [
            {
                "title": "My Thoughts on Python",
                "date": "2024-01-01",
                "content": "I think Python is the best language for rapid development.",
                "tags": ["python", "opinion"],
            }
        ]
        result = _format_evidence(posts)
        assert "## Blog Posts" in result
        assert "My Thoughts on Python" in result
        assert "python" in result

    def test_format_evidence_empty(self):
        from app.plugins.sources.blog import _format_evidence

        assert _format_evidence([]) == ""

    def test_normalize_date_iso(self):
        from app.plugins.sources.blog import _normalize_date

        assert _normalize_date("2024-03-15T12:00:00Z") == "2024-03-15"
        assert _normalize_date("2024-03-15") == "2024-03-15"

    def test_normalize_date_rfc2822(self):
        from app.plugins.sources.blog import _normalize_date

        result = _normalize_date("Mon, 01 Jan 2024 00:00:00 +0000")
        assert result == "2024-01-01"

    def test_normalize_date_empty(self):
        from app.plugins.sources.blog import _normalize_date

        assert _normalize_date("") == ""

    def test_strip_html(self):
        from app.plugins.sources.blog import _strip_html

        result = _strip_html("<p>Hello &amp; <b>world</b></p>")
        assert "<p>" not in result
        assert "<b>" not in result
        assert "&amp;" not in result
        assert "Hello" in result
        assert "world" in result

    def test_strip_html_empty(self):
        from app.plugins.sources.blog import _strip_html

        assert _strip_html("") == ""
        assert _strip_html(None) == ""  # type: ignore

    def test_find_feed_link(self):
        from app.plugins.sources.blog import _find_feed_link

        html = '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
        result = _find_feed_link(html, "https://example.com")
        assert result == "https://example.com/feed.xml"

    def test_find_feed_link_not_found(self):
        from app.plugins.sources.blog import _find_feed_link

        assert _find_feed_link("<html><body>no feed here</body></html>", "https://example.com") is None

    def test_extract_excerpt_prefers_opinion(self):
        from app.plugins.sources.blog import _extract_excerpt

        content = "This is a plain sentence. I think Python is great. Another plain sentence."
        excerpt = _extract_excerpt(content)
        # The excerpt should contain the opinion signal
        assert "I think Python" in excerpt

    def test_extract_excerpt_fallback(self):
        from app.plugins.sources.blog import _extract_excerpt

        content = "No opinions here. Just facts. Plain text."
        excerpt = _extract_excerpt(content)
        assert len(excerpt) > 0


# ---------------------------------------------------------------------------
# Claude Code Source
# ---------------------------------------------------------------------------


class TestClaudeCodeSource:
    def test_implements_ingestion_source(self):
        from app.plugins.sources.claude_code import ClaudeCodeSource

        assert isinstance(ClaudeCodeSource(), IngestionSource)

    def test_name(self):
        from app.plugins.sources.claude_code import ClaudeCodeSource

        assert ClaudeCodeSource.name == "claude_code"

    @pytest.mark.asyncio
    async def test_fetch_nonexistent_path(self):
        from app.plugins.sources.claude_code import ClaudeCodeSource

        result = await ClaudeCodeSource().fetch("/nonexistent/path/that/does/not/exist")
        assert isinstance(result, IngestionResult)
        assert result.stats["projects_discovered"] == 0

    @pytest.mark.asyncio
    async def test_fetch_jsonl_file(self):
        from app.plugins.sources.claude_code import ClaudeCodeSource

        entry = {
            "type": "user",
            "timestamp": "2024-01-01T10:00:00Z",
            "cwd": "/home/user/project",
            "message": {
                "role": "user",
                "content": "I think we should use Python for this because it has better libraries.",
            },
        }
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps(entry) + "\n")
            tmp_path = f.name

        try:
            result = await ClaudeCodeSource().fetch(tmp_path)
            assert isinstance(result, IngestionResult)
            assert result.stats["projects_discovered"] >= 1
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_extract_text_content_string(self):
        from app.plugins.sources.claude_code import _extract_text_content

        result = _extract_text_content("Hello world")
        assert result == ["Hello world"]

    def test_extract_text_content_list(self):
        from app.plugins.sources.claude_code import _extract_text_content

        content = [
            {"type": "text", "text": "Some message"},
            {"type": "tool_result", "content": "Should be ignored"},
            {"type": "text", "text": "Another message"},
        ]
        result = _extract_text_content(content)
        assert result == ["Some message", "Another message"]

    def test_extract_text_content_empty_string(self):
        from app.plugins.sources.claude_code import _extract_text_content

        assert _extract_text_content("") == []
        assert _extract_text_content("   ") == []

    def test_extract_text_content_invalid_type(self):
        from app.plugins.sources.claude_code import _extract_text_content

        assert _extract_text_content(None) == []  # type: ignore
        assert _extract_text_content(42) == []  # type: ignore

    def test_strip_code_blocks(self):
        from app.plugins.sources.claude_code import _strip_code_blocks

        text = "I prefer `React` for UI. ```python\nprint('hello')\n``` Use hooks."
        result = _strip_code_blocks(text)
        assert "```" not in result
        assert "print" not in result
        assert "I prefer" in result
        assert "`React`" in result  # short inline code preserved

    def test_strip_code_blocks_redacts_secrets(self):
        from app.plugins.sources.claude_code import _strip_code_blocks

        text = "Use this token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        result = _strip_code_blocks(text)
        assert "ghp_" not in result
        assert "[REDACTED]" in result

    def test_filter_messages_removes_short(self):
        from app.plugins.sources.claude_code import _filter_messages

        messages = [
            {"text": "ok", "has_personality": True, "has_decision": False, "has_architecture": False, "has_tech_mention": False, "timestamp": ""},
            {"text": "I think we should use Python for this project!", "has_personality": True, "has_decision": False, "has_architecture": False, "has_tech_mention": True, "timestamp": ""},
        ]
        result = _filter_messages(messages)
        assert len(result) == 1
        assert "Python" in result[0]["text"]

    def test_filter_messages_removes_commands(self):
        from app.plugins.sources.claude_code import _filter_messages

        messages = [
            {"text": "git commit -m test", "has_personality": False, "has_decision": False, "has_architecture": False, "has_tech_mention": False, "timestamp": ""},
            {"text": "I want to refactor this module", "has_personality": True, "has_decision": False, "has_architecture": False, "has_tech_mention": False, "timestamp": ""},
        ]
        result = _filter_messages(messages)
        assert len(result) == 1
        assert "refactor" in result[0]["text"]

    def test_filter_messages_removes_automated(self):
        from app.plugins.sources.claude_code import _filter_messages

        messages = [
            {"text": "# Ralph Loop running", "has_personality": True, "has_decision": False, "has_architecture": False, "has_tech_mention": False, "timestamp": ""},
            {"text": "I think we should refactor this", "has_personality": True, "has_decision": False, "has_architecture": False, "has_tech_mention": False, "timestamp": ""},
        ]
        result = _filter_messages(messages)
        assert len(result) == 1
        assert "refactor" in result[0]["text"]

    def test_is_automated_content(self):
        from app.plugins.sources.claude_code import _is_automated_content

        assert _is_automated_content("# Ralph Loop something")
        assert _is_automated_content("[Request interrupted by user]")
        assert not _is_automated_content("I think this is a good idea")

    def test_format_evidence_empty(self):
        from app.plugins.sources.claude_code import _format_evidence

        assert _format_evidence({}) == ""

    def test_format_evidence_with_messages(self):
        from app.plugins.sources.claude_code import _format_evidence

        projects = {
            "my-project": [
                {"text": "I prefer using TypeScript over JavaScript", "has_personality": True, "has_decision": False, "has_architecture": False, "has_tech_mention": True, "timestamp": ""},
                {"text": "Let's use a microservice architecture", "has_personality": False, "has_decision": True, "has_architecture": True, "has_tech_mention": False, "timestamp": ""},
            ]
        }
        result = _format_evidence(projects)
        assert "## Claude Code Conversations" in result
        assert "my-project" in result
        assert "TypeScript" in result

    def test_parse_jsonl(self):
        from app.plugins.sources.claude_code import _parse_jsonl

        entries = [
            {
                "type": "user",
                "timestamp": "2024-01-01T10:00:00Z",
                "cwd": "/project",
                "message": {
                    "role": "user",
                    "content": "I think we need to refactor this to use Python.",
                },
            },
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": "Sure, I can help."},
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
            tmp_path = f.name

        try:
            messages = _parse_jsonl(Path(tmp_path))
            assert len(messages) == 1
            assert "refactor" in messages[0]["text"]
            assert messages[0]["has_tech_mention"] is True
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_parse_jsonl_skips_bad_lines(self):
        from app.plugins.sources.claude_code import _parse_jsonl

        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write("not json at all\n")
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2024-01-01T00:00:00Z",
                "cwd": "/",
                "message": {"role": "user", "content": "I prefer TypeScript for large projects"},
            }) + "\n")
            tmp_path = f.name

        try:
            messages = _parse_jsonl(Path(tmp_path))
            assert len(messages) == 1
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_truncate(self):
        from app.plugins.sources.claude_code import _truncate

        assert _truncate("short", 100) == "short"
        assert _truncate("A" * 200, 100) == "A" * 100 + "..."


# ---------------------------------------------------------------------------
# DevBlog Source
# ---------------------------------------------------------------------------


class TestDevBlogSource:
    def test_implements_ingestion_source(self):
        from app.plugins.sources.devblog import DevBlogSource

        assert isinstance(DevBlogSource(), IngestionSource)

    def test_name(self):
        from app.plugins.sources.devblog import DevBlogSource

        assert DevBlogSource.name == "devblog"

    def test_format_evidence_basic(self):
        from app.plugins.sources.devblog import _format_evidence

        articles = [
            {
                "title": "Building with FastAPI",
                "published_at": "2024-01-15T00:00:00Z",
                "tag_list": ["python", "api", "fastapi"],
                "positive_reactions_count": 120,
                "comments_count": 15,
                "body_markdown": "FastAPI is my go-to framework for Python APIs.",
            }
        ]
        result = _format_evidence("ada", articles)
        assert "## Dev.to Articles" in result
        assert "Building with FastAPI" in result
        assert "python" in result
        assert "120 reactions" in result
        assert "FastAPI is my go-to" in result

    def test_format_evidence_empty(self):
        from app.plugins.sources.devblog import _format_evidence

        assert _format_evidence("nobody", []) == ""

    def test_format_evidence_truncates_long_body(self):
        from app.plugins.sources.devblog import _format_evidence

        articles = [
            {
                "title": "Long Article",
                "published_at": "2024-01-01T00:00:00Z",
                "tag_list": [],
                "positive_reactions_count": 0,
                "comments_count": 0,
                "body_markdown": "A" * 3000,
            }
        ]
        result = _format_evidence("user", articles)
        assert "..." in result

    def test_format_evidence_uses_description_fallback(self):
        from app.plugins.sources.devblog import _format_evidence

        articles = [
            {
                "title": "No Markdown",
                "published_at": "",
                "tag_list": [],
                "positive_reactions_count": 0,
                "comments_count": 0,
                "description": "Fallback description text",
            }
        ]
        result = _format_evidence("user", articles)
        assert "Fallback description text" in result

    def test_format_evidence_string_tags(self):
        from app.plugins.sources.devblog import _format_evidence

        articles = [
            {
                "title": "Tags as String",
                "published_at": "",
                "tag_list": "python, django, rest",
                "positive_reactions_count": 0,
                "comments_count": 0,
                "body_markdown": "Some content",
            }
        ]
        result = _format_evidence("user", articles)
        assert "python" in result
        assert "django" in result

    @pytest.mark.asyncio
    async def test_fetch_returns_ingestion_result(self):
        from app.plugins.sources.devblog import DevBlogSource

        articles = [
            {
                "id": 1,
                "title": "Test Article",
                "published_at": "2024-01-01T00:00:00Z",
                "tag_list": ["python"],
                "positive_reactions_count": 10,
                "comments_count": 2,
                "body_markdown": "Great content here.",
            }
        ]
        with (
            patch("app.plugins.sources.devblog._fetch_articles", AsyncMock(return_value=articles)),
            patch("app.plugins.sources.devblog._fetch_article_bodies", AsyncMock(return_value=articles)),
        ):
            result = await DevBlogSource().fetch("ada")

        assert isinstance(result, IngestionResult)
        assert result.source_name == "devblog"
        assert result.stats["articles_fetched"] == 1

    @pytest.mark.asyncio
    async def test_fetch_empty_returns_empty_evidence(self):
        from app.plugins.sources.devblog import DevBlogSource

        with (
            patch("app.plugins.sources.devblog._fetch_articles", AsyncMock(return_value=[])),
            patch("app.plugins.sources.devblog._fetch_article_bodies", AsyncMock(return_value=[])),
        ):
            result = await DevBlogSource().fetch("nobody")

        assert result.evidence == ""
        assert result.stats["articles_fetched"] == 0


# ---------------------------------------------------------------------------
# Website Source
# ---------------------------------------------------------------------------


class TestWebsiteSource:
    def test_implements_ingestion_source(self):
        from app.plugins.sources.website import WebsiteSource

        assert isinstance(WebsiteSource(), IngestionSource)

    def test_name(self):
        from app.plugins.sources.website import WebsiteSource

        assert WebsiteSource.name == "website"

    @pytest.mark.asyncio
    async def test_fetch_no_pages_found(self):
        from app.plugins.sources.website import WebsiteSource

        with patch("app.plugins.sources.website._discover_pages", AsyncMock(return_value=[])):
            result = await WebsiteSource().fetch("https://example.com")

        assert isinstance(result, IngestionResult)
        assert result.evidence == ""
        assert result.stats["page_count"] == 0
        assert "error" in result.raw_data

    @pytest.mark.asyncio
    async def test_fetch_with_pages(self):
        from app.plugins.sources.website import WebsiteSource

        pages = [{"title": "Home", "url": "https://example.com", "content": "Welcome to my site.", "word_count": 4}]
        with (
            patch("app.plugins.sources.website._discover_pages", AsyncMock(return_value=["https://example.com"])),
            patch("app.plugins.sources.website._extract_pages", return_value=pages),
        ):
            result = await WebsiteSource().fetch("https://example.com")

        assert isinstance(result, IngestionResult)
        assert result.stats["page_count"] == 1
        assert "Home" in result.evidence

    @pytest.mark.asyncio
    async def test_fetch_prepends_https(self):
        from app.plugins.sources.website import WebsiteSource

        with patch("app.plugins.sources.website._discover_pages", AsyncMock(return_value=[])) as mock_discover:
            await WebsiteSource().fetch("example.com")

        called_url = mock_discover.call_args[0][1]
        assert called_url.startswith("https://")

    def test_format_evidence_basic(self):
        from app.plugins.sources.website import _format_evidence

        pages = [
            {
                "title": "About Me",
                "url": "https://example.com/about",
                "content": "I am a Python developer who loves open source.",
            }
        ]
        result = _format_evidence(pages)
        assert "## Website Pages" in result
        assert "About Me" in result
        assert "https://example.com/about" in result
        assert "Python developer" in result

    def test_format_evidence_empty(self):
        from app.plugins.sources.website import _format_evidence

        assert _format_evidence([]) == ""

    def test_extract_internal_links(self):
        from app.plugins.sources.website import _extract_internal_links

        html = """
        <a href="/about">About</a>
        <a href="/blog/post-1">Post 1</a>
        <a href="https://other.com/page">External</a>
        <a href="/style.css">CSS</a>
        """
        links = _extract_internal_links(html, "https://example.com", "example.com")
        paths = [link.split("example.com")[1] for link in links]
        assert "/about" in paths
        assert "/blog/post-1" in paths
        # External link should not be included
        assert not any("other.com" in link for link in links)
        # CSS should be excluded
        assert not any(".css" in link for link in links)

    def test_title_from_url(self):
        from app.plugins.sources.website import _title_from_url

        assert _title_from_url("https://example.com/") == "Home"
        assert _title_from_url("https://example.com/about-me") == "About Me"
        assert _title_from_url("https://example.com/blog/my_post") == "My Post"


# ---------------------------------------------------------------------------
# Plugin Registry Integration
# ---------------------------------------------------------------------------


class TestPluginRegistration:
    def test_all_sources_registered(self):
        """Verify load_plugins() registers all 7 sources."""
        from app.plugins.registry import PluginRegistry
        from app.plugins.loader import load_plugins

        # Use a fresh registry to avoid interference from app startup
        fresh_registry = PluginRegistry()
        original_register = fresh_registry.register_source
        registered = []

        def capture_register(source):
            registered.append(source.name)
            original_register(source)

        fresh_registry.register_source = capture_register  # type: ignore

        # Patch the global registry used by load_plugins
        with patch("app.plugins.loader.registry", fresh_registry):
            load_plugins()

        expected = {"github", "claude_code", "blog", "stackoverflow", "devblog", "hackernews", "website"}
        assert expected.issubset(set(registered))

    def test_github_source_in_registry(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import PluginRegistry

        fresh_registry = PluginRegistry()
        with patch("app.plugins.loader.registry", fresh_registry):
            load_plugins()

        source = fresh_registry.get_source("github")
        assert source.name == "github"

    def test_hackernews_source_in_registry(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import PluginRegistry

        fresh_registry = PluginRegistry()
        with patch("app.plugins.loader.registry", fresh_registry):
            load_plugins()

        source = fresh_registry.get_source("hackernews")
        assert source.name == "hackernews"

    def test_stackoverflow_source_in_registry(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import PluginRegistry

        fresh_registry = PluginRegistry()
        with patch("app.plugins.loader.registry", fresh_registry):
            load_plugins()

        source = fresh_registry.get_source("stackoverflow")
        assert source.name == "stackoverflow"

    def test_blog_source_in_registry(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import PluginRegistry

        fresh_registry = PluginRegistry()
        with patch("app.plugins.loader.registry", fresh_registry):
            load_plugins()

        source = fresh_registry.get_source("blog")
        assert source.name == "blog"

    def test_devblog_source_in_registry(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import PluginRegistry

        fresh_registry = PluginRegistry()
        with patch("app.plugins.loader.registry", fresh_registry):
            load_plugins()

        source = fresh_registry.get_source("devblog")
        assert source.name == "devblog"

    def test_claude_code_source_in_registry(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import PluginRegistry

        fresh_registry = PluginRegistry()
        with patch("app.plugins.loader.registry", fresh_registry):
            load_plugins()

        source = fresh_registry.get_source("claude_code")
        assert source.name == "claude_code"

    def test_website_source_in_registry(self):
        from app.plugins.loader import load_plugins
        from app.plugins.registry import PluginRegistry

        fresh_registry = PluginRegistry()
        with patch("app.plugins.loader.registry", fresh_registry):
            load_plugins()

        source = fresh_registry.get_source("website")
        assert source.name == "website"
