"""Tests for fetch_items() on the 5 migrated ingestion sources (ALLIE-400).

Covers:
- Each source yields EvidenceItem objects with correct field shapes
- external_id prefixes match the spec
- item_type is correct per source
- content is non-empty
- privacy is "public" for all public sources
- since_external_ids filter skips matching IDs
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# BlogSource
# ---------------------------------------------------------------------------

_BLOG_RSS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Blog</title>
    <item>
      <title>Why I Love Python</title>
      <link>https://example.com/posts/why-i-love-python</link>
      <pubDate>Mon, 01 Jan 2024 00:00:00 +0000</pubDate>
      <description>Python is great because I think it reads like prose.</description>
    </item>
    <item>
      <title>Rust vs Go</title>
      <link>https://example.com/posts/rust-vs-go</link>
      <pubDate>Tue, 02 Jan 2024 00:00:00 +0000</pubDate>
      <description>I believe Rust is safer for systems programming.</description>
    </item>
  </channel>
</rss>
"""


class TestBlogSourceFetchItems:
    @pytest.mark.asyncio
    async def test_emits_post_items_with_correct_external_id(self):
        from app.plugins.sources.blog import BlogSource

        source = BlogSource()

        with patch(
            "app.plugins.sources.blog._resolve_feed",
            new=AsyncMock(return_value=("https://example.com/feed", _BLOG_RSS_XML)),
        ):
            items = []
            async for item in source.fetch_items("https://example.com", "mini-1", None):
                items.append(item)

        assert len(items) == 2
        for item in items:
            assert item.external_id.startswith("blog_post:")
            assert item.source_type == "blog"
            assert item.item_type == "post"
            assert item.context == "blog_post"
            assert item.content.strip()
            assert item.privacy == "public"

    @pytest.mark.asyncio
    async def test_external_ids_derived_from_url_path(self):
        from app.plugins.sources.blog import BlogSource

        source = BlogSource()

        with patch(
            "app.plugins.sources.blog._resolve_feed",
            new=AsyncMock(return_value=("https://example.com/feed", _BLOG_RSS_XML)),
        ):
            items = []
            async for item in source.fetch_items("https://example.com", "mini-1", None):
                items.append(item)

        external_ids = {i.external_id for i in items}
        # URL path "posts/why-i-love-python" → slug "posts_why-i-love-python"
        assert any("why-i-love-python" in eid for eid in external_ids)

    @pytest.mark.asyncio
    async def test_since_filter_skips_matching_ids(self):
        from app.plugins.sources.blog import BlogSource

        source = BlogSource()

        with patch(
            "app.plugins.sources.blog._resolve_feed",
            new=AsyncMock(return_value=("https://example.com/feed", _BLOG_RSS_XML)),
        ):
            # First collect all items to get real external IDs
            all_items = []
            async for item in source.fetch_items("https://example.com", "mini-1", None):
                all_items.append(item)

        assert len(all_items) == 2
        first_id = all_items[0].external_id

        with patch(
            "app.plugins.sources.blog._resolve_feed",
            new=AsyncMock(return_value=("https://example.com/feed", _BLOG_RSS_XML)),
        ):
            filtered_items = []
            async for item in source.fetch_items(
                "https://example.com", "mini-1", None, since_external_ids={first_id}
            ):
                filtered_items.append(item)

        assert len(filtered_items) == 1
        assert filtered_items[0].external_id != first_id

    @pytest.mark.asyncio
    async def test_no_feed_yields_nothing(self):
        from app.plugins.sources.blog import BlogSource

        source = BlogSource()

        with patch(
            "app.plugins.sources.blog._resolve_feed",
            new=AsyncMock(return_value=("https://example.com", None)),
        ):
            items = []
            async for item in source.fetch_items("https://example.com", "mini-1", None):
                items.append(item)

        assert items == []


# ---------------------------------------------------------------------------
# HackerNewsSource
# ---------------------------------------------------------------------------

_FAKE_HN_COMMENTS = [
    {
        "objectID": "111",
        "comment_text": "<p>I disagree with this approach</p>",
        "story_title": "Ask HN: How do you structure code?",
        "points": 10,
    },
    {
        "objectID": "222",
        "comment_text": "<p>This is an interesting observation</p>",
        "story_title": "Show HN: My new project",
        "points": 5,
    },
]

_FAKE_HN_STORIES = [
    {
        "objectID": "333",
        "title": "I built a new parser",
        "url": "https://example.com/parser",
        "points": 42,
        "num_comments": 15,
    }
]


class TestHackerNewsSourceFetchItems:
    @pytest.mark.asyncio
    async def test_emits_comment_items(self):
        from app.plugins.sources.hackernews import HackerNewsSource

        source = HackerNewsSource()

        with patch(
            "app.plugins.sources.hackernews._fetch_hn_data",
            new=AsyncMock(return_value=(_FAKE_HN_COMMENTS, _FAKE_HN_STORIES)),
        ):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", None):
                items.append(item)

        comment_items = [i for i in items if i.item_type == "comment"]
        assert len(comment_items) == 2
        for item in comment_items:
            assert item.external_id.startswith("hn:")
            assert item.source_type == "hackernews"
            assert item.context == "hackernews_comment"
            assert item.content.strip()
            assert item.privacy == "public"

    @pytest.mark.asyncio
    async def test_emits_story_items(self):
        from app.plugins.sources.hackernews import HackerNewsSource

        source = HackerNewsSource()

        with patch(
            "app.plugins.sources.hackernews._fetch_hn_data",
            new=AsyncMock(return_value=(_FAKE_HN_COMMENTS, _FAKE_HN_STORIES)),
        ):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", None):
                items.append(item)

        story_items = [i for i in items if i.item_type == "story"]
        assert len(story_items) == 1
        assert story_items[0].external_id == "hn:333"
        assert story_items[0].context == "hackernews_story"
        assert story_items[0].privacy == "public"

    @pytest.mark.asyncio
    async def test_external_id_format(self):
        from app.plugins.sources.hackernews import HackerNewsSource

        source = HackerNewsSource()

        with patch(
            "app.plugins.sources.hackernews._fetch_hn_data",
            new=AsyncMock(return_value=(_FAKE_HN_COMMENTS, [])),
        ):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", None):
                items.append(item)

        external_ids = {i.external_id for i in items}
        assert "hn:111" in external_ids
        assert "hn:222" in external_ids

    @pytest.mark.asyncio
    async def test_since_filter_skips_known_items(self):
        from app.plugins.sources.hackernews import HackerNewsSource

        source = HackerNewsSource()

        with patch(
            "app.plugins.sources.hackernews._fetch_hn_data",
            new=AsyncMock(return_value=(_FAKE_HN_COMMENTS, _FAKE_HN_STORIES)),
        ):
            items = []
            async for item in source.fetch_items(
                "testuser", "mini-1", None, since_external_ids={"hn:111", "hn:333"}
            ):
                items.append(item)

        external_ids = {i.external_id for i in items}
        assert "hn:111" not in external_ids
        assert "hn:333" not in external_ids
        assert "hn:222" in external_ids


# ---------------------------------------------------------------------------
# StackOverflowSource
# ---------------------------------------------------------------------------

_FAKE_SO_ANSWERS = [
    {
        "answer_id": 100001,
        "question_id": 200001,
        "_question_title": "How to reverse a list in Python?",
        "tags": ["python", "list"],
        "score": 50,
        "is_accepted": True,
        "body": "<p>Use <code>list[::-1]</code> for a reversed copy.</p>",
    },
    {
        "answer_id": 100002,
        "question_id": 200002,
        "_question_title": "Difference between == and is in Python?",
        "tags": ["python"],
        "score": 30,
        "is_accepted": False,
        "body": "<p>== compares values, is compares identity.</p>",
    },
]


class TestStackOverflowSourceFetchItems:
    @pytest.mark.asyncio
    async def test_emits_answer_items(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()

        with (
            patch.object(source, "_resolve_user_id", new=AsyncMock(return_value=12345)),
            patch.object(
                source, "_fetch_top_answers", new=AsyncMock(return_value=_FAKE_SO_ANSWERS)
            ),
        ):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", None):
                items.append(item)

        assert len(items) == 2
        for item in items:
            assert item.external_id.startswith("so:")
            assert item.source_type == "stackoverflow"
            assert item.item_type == "answer"
            assert item.context == "stackoverflow_answer"
            assert item.content.strip()
            assert item.privacy == "public"

    @pytest.mark.asyncio
    async def test_external_id_format(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()

        with (
            patch.object(source, "_resolve_user_id", new=AsyncMock(return_value=12345)),
            patch.object(
                source, "_fetch_top_answers", new=AsyncMock(return_value=_FAKE_SO_ANSWERS)
            ),
        ):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", None):
                items.append(item)

        external_ids = {i.external_id for i in items}
        assert "so:100001" in external_ids
        assert "so:100002" in external_ids

    @pytest.mark.asyncio
    async def test_content_includes_question_and_answer(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()

        with (
            patch.object(source, "_resolve_user_id", new=AsyncMock(return_value=12345)),
            patch.object(
                source, "_fetch_top_answers", new=AsyncMock(return_value=_FAKE_SO_ANSWERS[:1])
            ),
        ):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", None):
                items.append(item)

        assert len(items) == 1
        assert "How to reverse a list" in items[0].content
        assert "reversed copy" in items[0].content

    @pytest.mark.asyncio
    async def test_since_filter_skips_known_answers(self):
        from app.plugins.sources.stackoverflow import StackOverflowSource

        source = StackOverflowSource()

        with (
            patch.object(source, "_resolve_user_id", new=AsyncMock(return_value=12345)),
            patch.object(
                source, "_fetch_top_answers", new=AsyncMock(return_value=_FAKE_SO_ANSWERS)
            ),
        ):
            items = []
            async for item in source.fetch_items(
                "testuser", "mini-1", None, since_external_ids={"so:100001"}
            ):
                items.append(item)

        assert len(items) == 1
        assert items[0].external_id == "so:100002"


# ---------------------------------------------------------------------------
# DevBlogSource (Dev.to)
# ---------------------------------------------------------------------------

_FAKE_DEVTO_ARTICLES = [
    {
        "id": 501,
        "title": "Building APIs with FastAPI",
        "published_at": "2024-03-01T00:00:00Z",
        "tag_list": ["python", "fastapi", "api"],
        "positive_reactions_count": 120,
        "comments_count": 18,
        "body_markdown": "# FastAPI\n\nFastAPI is my preferred framework because it's fast and easy.",
    },
    {
        "id": 502,
        "title": "Why I switched to TypeScript",
        "published_at": "2024-04-01T00:00:00Z",
        "tag_list": ["typescript", "javascript"],
        "positive_reactions_count": 80,
        "comments_count": 10,
        "body_markdown": "# TypeScript\n\nTypeScript catches bugs that JavaScript misses.",
    },
]


class TestDevBlogSourceFetchItems:
    @pytest.mark.asyncio
    async def test_emits_article_items(self):
        from app.plugins.sources.devblog import DevBlogSource

        source = DevBlogSource()

        with (
            patch(
                "app.plugins.sources.devblog._fetch_articles",
                new=AsyncMock(return_value=_FAKE_DEVTO_ARTICLES),
            ),
            patch(
                "app.plugins.sources.devblog._fetch_article_bodies",
                new=AsyncMock(return_value=_FAKE_DEVTO_ARTICLES),
            ),
        ):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", None):
                items.append(item)

        assert len(items) == 2
        for item in items:
            assert item.external_id.startswith("devto:")
            assert item.source_type == "devblog"
            assert item.item_type == "article"
            assert item.context == "devto_article"
            assert item.content.strip()
            assert item.privacy == "public"

    @pytest.mark.asyncio
    async def test_external_id_format(self):
        from app.plugins.sources.devblog import DevBlogSource

        source = DevBlogSource()

        with (
            patch(
                "app.plugins.sources.devblog._fetch_articles",
                new=AsyncMock(return_value=_FAKE_DEVTO_ARTICLES),
            ),
            patch(
                "app.plugins.sources.devblog._fetch_article_bodies",
                new=AsyncMock(return_value=_FAKE_DEVTO_ARTICLES),
            ),
        ):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", None):
                items.append(item)

        external_ids = {i.external_id for i in items}
        assert "devto:501" in external_ids
        assert "devto:502" in external_ids

    @pytest.mark.asyncio
    async def test_content_includes_title_and_body(self):
        from app.plugins.sources.devblog import DevBlogSource

        source = DevBlogSource()

        with (
            patch(
                "app.plugins.sources.devblog._fetch_articles",
                new=AsyncMock(return_value=_FAKE_DEVTO_ARTICLES[:1]),
            ),
            patch(
                "app.plugins.sources.devblog._fetch_article_bodies",
                new=AsyncMock(return_value=_FAKE_DEVTO_ARTICLES[:1]),
            ),
        ):
            items = []
            async for item in source.fetch_items("testuser", "mini-1", None):
                items.append(item)

        assert len(items) == 1
        assert "Building APIs with FastAPI" in items[0].content
        assert "FastAPI" in items[0].content

    @pytest.mark.asyncio
    async def test_since_filter_skips_known_articles(self):
        from app.plugins.sources.devblog import DevBlogSource

        source = DevBlogSource()

        with (
            patch(
                "app.plugins.sources.devblog._fetch_articles",
                new=AsyncMock(return_value=_FAKE_DEVTO_ARTICLES),
            ),
            patch(
                "app.plugins.sources.devblog._fetch_article_bodies",
                new=AsyncMock(return_value=_FAKE_DEVTO_ARTICLES),
            ),
        ):
            items = []
            async for item in source.fetch_items(
                "testuser", "mini-1", None, since_external_ids={"devto:501"}
            ):
                items.append(item)

        assert len(items) == 1
        assert items[0].external_id == "devto:502"


# ---------------------------------------------------------------------------
# WebsiteSource
# ---------------------------------------------------------------------------

_FAKE_WEBSITE_PAGES = [
    {
        "title": "About Me",
        "url": "https://example.com/about",
        "content": "I am a software engineer who loves open source.",
        "word_count": 10,
    },
    {
        "title": "Projects",
        "url": "https://example.com/projects",
        "content": "Here are some projects I have built over the years.",
        "word_count": 10,
    },
]


class TestWebsiteSourceFetchItems:
    @pytest.mark.asyncio
    async def test_emits_page_items(self):
        from app.plugins.sources.website import WebsiteSource

        source = WebsiteSource()

        with (
            patch(
                "app.plugins.sources.website._discover_pages",
                new=AsyncMock(
                    return_value=["https://example.com/about", "https://example.com/projects"]
                ),
            ),
            patch("app.plugins.sources.website._extract_pages", return_value=_FAKE_WEBSITE_PAGES),
        ):
            items = []
            async for item in source.fetch_items("https://example.com", "mini-1", None):
                items.append(item)

        assert len(items) == 2
        for item in items:
            assert item.external_id.startswith("website:")
            assert item.source_type == "website"
            assert item.item_type == "page"
            assert item.context == "website_page"
            assert item.content.strip()
            assert item.privacy == "public"

    @pytest.mark.asyncio
    async def test_external_id_derived_from_path(self):
        from app.plugins.sources.website import WebsiteSource

        source = WebsiteSource()

        with (
            patch(
                "app.plugins.sources.website._discover_pages",
                new=AsyncMock(return_value=["https://example.com/about"]),
            ),
            patch(
                "app.plugins.sources.website._extract_pages", return_value=[_FAKE_WEBSITE_PAGES[0]]
            ),
        ):
            items = []
            async for item in source.fetch_items("https://example.com", "mini-1", None):
                items.append(item)

        assert len(items) == 1
        assert items[0].external_id == "website:about"

    @pytest.mark.asyncio
    async def test_homepage_gets_hash_slug(self):
        from app.plugins.sources.website import WebsiteSource

        source = WebsiteSource()

        homepage_page = {
            "title": "Home",
            "url": "https://example.com",
            "content": "Welcome to my personal site.",
            "word_count": 5,
        }

        with (
            patch(
                "app.plugins.sources.website._discover_pages",
                new=AsyncMock(return_value=["https://example.com"]),
            ),
            patch("app.plugins.sources.website._extract_pages", return_value=[homepage_page]),
        ):
            items = []
            async for item in source.fetch_items("https://example.com", "mini-1", None):
                items.append(item)

        assert len(items) == 1
        # Homepage: path is empty, should use hash
        assert items[0].external_id.startswith("website:")
        slug = items[0].external_id[len("website:") :]
        assert len(slug) == 16  # SHA-256 prefix

    @pytest.mark.asyncio
    async def test_since_filter_skips_known_pages(self):
        from app.plugins.sources.website import WebsiteSource

        source = WebsiteSource()

        with (
            patch(
                "app.plugins.sources.website._discover_pages",
                new=AsyncMock(
                    return_value=["https://example.com/about", "https://example.com/projects"]
                ),
            ),
            patch("app.plugins.sources.website._extract_pages", return_value=_FAKE_WEBSITE_PAGES),
        ):
            items = []
            async for item in source.fetch_items(
                "https://example.com", "mini-1", None, since_external_ids={"website:about"}
            ):
                items.append(item)

        assert len(items) == 1
        assert items[0].external_id == "website:projects"

    @pytest.mark.asyncio
    async def test_no_pages_yields_nothing(self):
        from app.plugins.sources.website import WebsiteSource

        source = WebsiteSource()

        with patch("app.plugins.sources.website._discover_pages", new=AsyncMock(return_value=[])):
            items = []
            async for item in source.fetch_items("https://example.com", "mini-1", None):
                items.append(item)

        assert items == []
