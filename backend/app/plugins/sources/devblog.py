"""Dev.to blog ingestion source plugin.

Fetches a developer's published articles from the Dev.to API and formats them
as evidence for personality analysis. Blog posts reveal in-depth technical
knowledge, teaching style, and opinions on technology choices.

Also fetches article comments to surface community interaction patterns:
how the author engages with readers reveals communication style and values.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.plugins.base import IngestionResult, IngestionSource

logger = logging.getLogger(__name__)

_DEVTO_API = "https://dev.to/api"
_MAX_ARTICLES = 30
_EXCERPT_LENGTH = 1500
_MAX_COMMENTS_PER_ARTICLE = 5  # author's own comments in discussion threads


class DevBlogSource(IngestionSource):
    """Ingestion source that fetches Dev.to articles for a username."""

    name = "devblog"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch Dev.to articles (with full body + comments) and format as evidence.

        Fetches article body content, reactions/engagement metrics, and the author's
        own comments in discussion threads (to reveal how they engage with readers).

        Args:
            identifier: Dev.to username.
        """
        max_articles = config.get("max_articles", _MAX_ARTICLES)

        async with httpx.AsyncClient(timeout=30) as client:
            articles = await _fetch_articles(client, identifier, max_articles)
            detailed = await _fetch_article_bodies(client, articles)
            # Fetch author comments on their own articles concurrently
            author_comments = await _fetch_author_comments(client, identifier, detailed)

        evidence = _format_evidence(identifier, detailed, author_comments)

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={
                "article_count": len(detailed),
                "articles": [
                    {
                        "title": a["title"],
                        "tags": a.get("tag_list", []),
                        "published_at": a.get("published_at", ""),
                        "positive_reactions_count": a.get("positive_reactions_count", 0),
                        "comments_count": a.get("comments_count", 0),
                    }
                    for a in detailed
                ],
                "author_comments_count": sum(len(v) for v in author_comments.values()),
            },
            stats={
                "articles_fetched": len(detailed),
                "total_reactions": sum(a.get("positive_reactions_count", 0) for a in detailed),
                "total_comments": sum(a.get("comments_count", 0) for a in detailed),
                "author_comments_fetched": sum(len(v) for v in author_comments.values()),
                "evidence_length": len(evidence),
            },
        )


async def _fetch_articles(
    client: httpx.AsyncClient, username: str, limit: int
) -> list[dict[str, Any]]:
    """Fetch article listing for a Dev.to user."""
    articles: list[dict[str, Any]] = []
    page = 1
    per_page = min(limit, 30)

    while len(articles) < limit:
        resp = await client.get(
            f"{_DEVTO_API}/articles",
            params={"username": username, "per_page": per_page, "page": page},
        )
        if resp.status_code != 200:
            logger.warning("Dev.to API returned %d for user %s", resp.status_code, username)
            break

        batch = resp.json()
        if not batch:
            break

        articles.extend(batch)
        page += 1

    return articles[:limit]


async def _fetch_article_bodies(
    client: httpx.AsyncClient, articles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fetch full body_markdown for each article."""
    detailed: list[dict[str, Any]] = []

    for article in articles:
        article_id = article.get("id")
        if not article_id:
            continue

        try:
            resp = await client.get(f"{_DEVTO_API}/articles/{article_id}")
            if resp.status_code == 200:
                detailed.append(resp.json())
            else:
                # Fall back to listing data (no body_markdown)
                detailed.append(article)
        except httpx.HTTPError:
            logger.warning("Failed to fetch Dev.to article %s", article_id)
            detailed.append(article)

    return detailed


async def _fetch_author_comments(
    client: httpx.AsyncClient,
    username: str,
    articles: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    """Fetch comments on each article, keeping only the author's own replies.

    The author's comments in their own article threads reveal how they engage
    with readers — whether they're patient, dismissive, detailed, humorous, etc.
    This is high-signal personality data.
    """
    sem = asyncio.Semaphore(5)

    async def _fetch_for_article(article: dict) -> tuple[int, list[dict]]:
        article_id = article.get("id")
        if not article_id or not article.get("comments_count", 0):
            return article_id or 0, []

        async with sem:
            try:
                resp = await client.get(
                    f"{_DEVTO_API}/comments",
                    params={"a_id": article_id},
                )
                if resp.status_code != 200:
                    return article_id, []
                all_comments = resp.json()
                # Keep only comments by the article author
                author_comments = [
                    c for c in all_comments
                    if (c.get("user") or {}).get("username", "").lower() == username.lower()
                ]
                return article_id, author_comments[:_MAX_COMMENTS_PER_ARTICLE]
            except httpx.HTTPError:
                return article_id, []

    results = await asyncio.gather(*[_fetch_for_article(a) for a in articles])
    return {aid: comments for aid, comments in results if comments}


def _format_evidence(
    username: str,
    articles: list[dict[str, Any]],
    author_comments: dict[int, list[dict[str, Any]]] | None = None,
) -> str:
    """Format Dev.to articles (with body content and author comments) into evidence text."""
    if not articles:
        return ""

    author_comments = author_comments or {}

    sections: list[str] = [
        "## Dev.to Articles\n"
        "(Developer blog posts reveal in-depth technical knowledge, teaching style,\n"
        "and opinions on technology choices. Author comments show how they engage with readers.)\n"
    ]

    for article in articles:
        article_id = article.get("id", 0)
        title = article.get("title", "Untitled")
        published = article.get("published_at", "")[:10]
        tags = article.get("tag_list") or article.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        tag_str = ", ".join(tags) if tags else "untagged"
        reactions = article.get("positive_reactions_count", 0)
        comments_count = article.get("comments_count", 0)

        body = article.get("body_markdown") or article.get("description") or ""
        excerpt = body[:_EXCERPT_LENGTH]
        if len(body) > _EXCERPT_LENGTH:
            excerpt += "..."

        sections.append(
            f'### "{title}" ({published}) [{tag_str}] '
            f"({reactions} reactions, {comments_count} comments)"
        )
        if excerpt:
            sections.append(f"> {excerpt}")

        # Include author's own comments in the discussion thread
        article_author_comments = author_comments.get(article_id, [])
        if article_author_comments:
            sections.append("*Author's replies in discussion:*")
            for comment in article_author_comments:
                body_html = comment.get("body_html", "") or comment.get("body", "")
                # Strip basic HTML tags from comment body
                import re
                comment_text = re.sub(r"<[^>]+>", " ", body_html).strip()
                comment_text = " ".join(comment_text.split())
                if comment_text:
                    if len(comment_text) > 400:
                        comment_text = comment_text[:400] + "..."
                    sections.append(f'  - "{comment_text}"')

        sections.append("")

    return "\n".join(sections)
