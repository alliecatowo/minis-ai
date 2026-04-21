"""HackerNews ingestion source plugin — fetches comments and submissions via Algolia API."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.plugins.base import EvidenceItem, IngestionSource

_HN_API_BASE = "https://hn.algolia.com/api/v1"


class HackerNewsSource(IngestionSource):
    """Ingestion source that fetches HackerNews activity for a username."""

    name = "hackernews"

    async def fetch_items(
        self,
        identifier: str,
        mini_id: str,
        session: Any,
        *,
        since_external_ids: set[str] | None = None,
    ) -> AsyncIterator[EvidenceItem]:
        """Yield one EvidenceItem per HN comment or story submission.

        external_id: ``hn:{item_id}`` where item_id is the Algolia objectID.
        Items already present in ``since_external_ids`` are skipped.
        """
        since = since_external_ids or set()

        async with httpx.AsyncClient(timeout=30.0) as client:
            comments, stories = await _fetch_hn_data(client, identifier)

        for story in stories:
            item_id = story.get("objectID") or story.get("story_id") or ""
            if not item_id:
                continue
            external_id = f"hn:{item_id}"
            if external_id in since:
                continue

            title = story.get("title") or ""
            url = story.get("url") or ""
            points = story.get("points") or 0
            num_comments = story.get("num_comments") or 0

            content_parts: list[str] = []
            if title:
                content_parts.append(f"Story: {title}")
            if url:
                content_parts.append(f"URL: {url}")
            content_parts.append(f"Points: {points}, Comments: {num_comments}")

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="story",
                content="\n".join(content_parts),
                context="hackernews_story",
                metadata={"title": title, "url": url, "points": points},
                privacy="public",
            )

        for comment in comments:
            item_id = comment.get("objectID") or comment.get("comment_id") or ""
            if not item_id:
                continue
            external_id = f"hn:{item_id}"
            if external_id in since:
                continue

            text = (comment.get("comment_text") or "").strip()
            if not text:
                continue
            clean_text = _strip_html(text)
            story_title = comment.get("story_title") or ""

            content_parts = []
            if story_title:
                content_parts.append(f"On: {story_title}")
            content_parts.append(clean_text)

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="comment",
                content="\n".join(content_parts),
                context="hackernews_comment",
                metadata={"story_title": story_title, "points": comment.get("points")},
                privacy="public",
            )


async def _fetch_hn_data(client: httpx.AsyncClient, username: str) -> tuple[list[dict], list[dict]]:
    """Fetch comments and story submissions for a HN user in parallel."""
    comments_url = f"{_HN_API_BASE}/search?tags=comment,author_{username}&hitsPerPage=100"
    stories_url = f"{_HN_API_BASE}/search?tags=story,author_{username}&hitsPerPage=50"

    comments_resp, stories_resp = await _parallel_get(client, comments_url, stories_url)

    comments = comments_resp.get("hits", []) if comments_resp else []
    stories = stories_resp.get("hits", []) if stories_resp else []

    return comments, stories


async def _parallel_get(client: httpx.AsyncClient, *urls: str) -> list[dict | None]:
    """GET multiple URLs concurrently, returning parsed JSON or None on failure."""
    import asyncio

    async def _get(url: str) -> dict | None:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError):
            return None

    return list(await asyncio.gather(*[_get(u) for u in urls]))


def _strip_html(text: str) -> str:
    """Remove HTML tags from HN comment text."""
    # Replace common HTML entities and tags
    text = text.replace("<p>", "\n\n").replace("</p>", "")
    text = text.replace("<i>", "_").replace("</i>", "_")
    text = text.replace("<b>", "**").replace("</b>", "**")
    text = text.replace("<code>", "`").replace("</code>", "`")
    text = text.replace("<pre>", "```\n").replace("</pre>", "\n```")
    text = text.replace("&gt;", ">").replace("&lt;", "<")
    text = text.replace("&amp;", "&").replace("&quot;", '"')
    text = text.replace("&#x27;", "'").replace("&#x2F;", "/")
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()
