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

from app.plugins.base import IngestionSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_github_data(**kwargs):
    """Create a minimal GitHubData for testing.

    Also attaches extended GitHub activity fields as plain attributes to simulate
    data that the GitHubSource plugin accesses (these may or may not be
    dataclass fields depending on the version).
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
            {
                "body": "I disagree with this approach, we should use recursion.",
                "path": "engine.py",
                "diff_hunk": "",
            },
            {"body": "LGTM", "path": "README.md", "diff_hunk": ""},
        ],
        "issue_comments": [
            {
                "body": "This is a known issue, however, there is a workaround.",
                "html_url": "https://github.com/ada/engine/issues/1",
            }
        ],
        "pull_request_reviews": [],
        "repo_languages": {"ada/engine": {"Python": 50000, "C": 10000}},
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

    def test_strip_html(self):
        from app.plugins.sources.hackernews import _strip_html

        html = "<p>Hello &amp; <b>world</b></p>"
        result = _strip_html(html)
        assert "<p>" not in result
        assert "<b>" not in result
        assert "&amp;" not in result
        assert "Hello" in result
        assert "world" in result


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
        mock_resp.json.return_value = {"items": [{"display_name": "Ada", "user_id": 99}]}
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

        assert (
            _find_feed_link("<html><body>no feed here</body></html>", "https://example.com") is None
        )


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
            {
                "text": "ok",
                "has_personality": True,
                "has_decision": False,
                "has_architecture": False,
                "has_tech_mention": False,
                "timestamp": "",
            },
            {
                "text": "I think we should use Python for this project!",
                "has_personality": True,
                "has_decision": False,
                "has_architecture": False,
                "has_tech_mention": True,
                "timestamp": "",
            },
        ]
        result = _filter_messages(messages)
        assert len(result) == 1
        assert "Python" in result[0]["text"]

    def test_filter_messages_removes_commands(self):
        from app.plugins.sources.claude_code import _filter_messages

        messages = [
            {
                "text": "git commit -m test",
                "has_personality": False,
                "has_decision": False,
                "has_architecture": False,
                "has_tech_mention": False,
                "timestamp": "",
            },
            {
                "text": "I want to refactor this module",
                "has_personality": True,
                "has_decision": False,
                "has_architecture": False,
                "has_tech_mention": False,
                "timestamp": "",
            },
        ]
        result = _filter_messages(messages)
        assert len(result) == 1
        assert "refactor" in result[0]["text"]

    def test_filter_messages_removes_automated(self):
        from app.plugins.sources.claude_code import _filter_messages

        messages = [
            {
                "text": "# Ralph Loop running",
                "has_personality": True,
                "has_decision": False,
                "has_architecture": False,
                "has_tech_mention": False,
                "timestamp": "",
            },
            {
                "text": "I think we should refactor this",
                "has_personality": True,
                "has_decision": False,
                "has_architecture": False,
                "has_tech_mention": False,
                "timestamp": "",
            },
        ]
        result = _filter_messages(messages)
        assert len(result) == 1
        assert "refactor" in result[0]["text"]

    def test_is_automated_content(self):
        from app.plugins.sources.claude_code import _is_automated_content

        assert _is_automated_content("# Ralph Loop something")
        assert _is_automated_content("[Request interrupted by user]")
        assert not _is_automated_content("I think this is a good idea")

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
            f.write(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": "2024-01-01T00:00:00Z",
                        "cwd": "/",
                        "message": {
                            "role": "user",
                            "content": "I prefer TypeScript for large projects",
                        },
                    }
                )
                + "\n"
            )
            tmp_path = f.name

        try:
            messages = _parse_jsonl(Path(tmp_path))
            assert len(messages) == 1
        finally:
            Path(tmp_path).unlink(missing_ok=True)


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

        expected = {
            "github",
            "claude_code",
            "blog",
            "stackoverflow",
            "devblog",
            "hackernews",
            "website",
        }
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
