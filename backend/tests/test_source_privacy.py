"""Tests for source-level default_privacy mapping.

Verifies that each ingestion source advertises the correct privacy tier:
- github, blog, hackernews, stackoverflow, devblog, website -> 'public'
- claude_code -> 'private'
"""

from __future__ import annotations


from app.plugins.base import IngestionSource


class TestDefaultPrivacyAttribute:
    def test_base_class_default_is_public(self):
        """IngestionSource.default_privacy defaults to 'public'."""
        assert IngestionSource.default_privacy == "public"

    def test_github_is_public(self):
        from app.plugins.sources.github import GitHubSource

        src = GitHubSource()
        assert src.default_privacy == "public"

    def test_claude_code_is_private(self):
        from app.plugins.sources.claude_code import ClaudeCodeSource

        src = ClaudeCodeSource()
        assert src.default_privacy == "private"

    def test_blog_is_public(self):
        from app.plugins.sources.blog import BlogSource

        src = BlogSource()
        assert src.default_privacy == "public"

    def test_hackernews_is_public(self):
        from app.plugins.sources.hackernews import HackerNewsSource

        src = HackerNewsSource()
        assert src.default_privacy == "public"

    def test_stackoverflow_is_public(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        src = StackOverflowSource()
        assert src.default_privacy == "public"

    def test_website_is_public(self):
        from app.plugins.sources.website import WebsiteSource

        src = WebsiteSource()
        assert src.default_privacy == "public"
