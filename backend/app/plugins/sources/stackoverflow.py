"""Stack Overflow ingestion source plugin — fetches top answers for personality analysis."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from html import unescape
from typing import Any

import httpx

from app.plugins.base import EvidenceItem, IngestionSource

_API_BASE = "https://api.stackexchange.com/2.3"
_DEFAULT_SITE = "stackoverflow"
_PAGE_SIZE = 50


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities to plain text."""
    text = re.sub(r"<[^>]+>", "", html)
    return unescape(text).strip()


class StackOverflowSource(IngestionSource):
    """Ingestion source that fetches Stack Overflow answers for a user."""

    name = "stackoverflow"

    async def fetch_items(
        self,
        identifier: str,
        mini_id: str,
        session: Any,
        *,
        since_external_ids: set[str] | None = None,
    ) -> AsyncIterator[EvidenceItem]:
        """Yield one EvidenceItem per Stack Overflow answer.

        external_id: ``so:{answer_id}``
        Items already present in ``since_external_ids`` are skipped.
        """
        since = since_external_ids or set()

        async with httpx.AsyncClient(timeout=30) as client:
            user_id = await self._resolve_user_id(client, identifier)
            answers = await self._fetch_top_answers(client, user_id)

        for answer in answers:
            answer_id = answer.get("answer_id")
            if not answer_id:
                continue
            external_id = f"so:{answer_id}"
            if external_id in since:
                continue

            question_title = answer.get("_question_title") or "Unknown Question"
            tags = answer.get("tags") or []
            score = answer.get("score", 0)
            accepted = answer.get("is_accepted", False)
            body_html = answer.get("body") or ""
            body_text = _strip_html(body_html)

            content_parts: list[str] = []
            content_parts.append(f"Question: {question_title}")
            if tags:
                content_parts.append(f"Tags: {', '.join(tags)}")
            content_parts.append(f"Score: {score}" + (", Accepted" if accepted else ""))
            if body_text:
                content_parts.append(body_text)

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="answer",
                content="\n".join(content_parts),
                metadata={
                    "answer_id": answer_id,
                    "question_title": question_title,
                    "tags": tags,
                    "score": score,
                    "is_accepted": accepted,
                },
                privacy="public",
            )

    async def _resolve_user_id(self, client: httpx.AsyncClient, identifier: str) -> int:
        """Resolve a display name to a numeric user ID, or validate a numeric ID."""
        if identifier.isdigit():
            return int(identifier)

        resp = await client.get(
            f"{_API_BASE}/users",
            params={
                "inname": identifier,
                "site": _DEFAULT_SITE,
                "pagesize": 5,
                "order": "desc",
                "sort": "reputation",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])

        if not items:
            raise ValueError(f"No Stack Overflow user found matching '{identifier}'")

        # Prefer exact display_name match (case-insensitive), fall back to top result
        for user in items:
            if user.get("display_name", "").lower() == identifier.lower():
                return user["user_id"]
        return items[0]["user_id"]

    async def _fetch_top_answers(self, client: httpx.AsyncClient, user_id: int) -> list[dict]:
        """Fetch top-voted answers with full body text."""
        resp = await client.get(
            f"{_API_BASE}/users/{user_id}/answers",
            params={
                "order": "desc",
                "sort": "votes",
                "site": _DEFAULT_SITE,
                "filter": "withbody",
                "pagesize": _PAGE_SIZE,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        answers = data.get("items", [])

        # Batch-fetch question titles for all answers
        question_ids = [a["question_id"] for a in answers if "question_id" in a]
        titles = await self._fetch_question_titles(client, question_ids)

        for answer in answers:
            qid = answer.get("question_id")
            answer["_question_title"] = titles.get(qid, "Unknown Question")

        return answers

    async def _fetch_question_titles(
        self, client: httpx.AsyncClient, question_ids: list[int]
    ) -> dict[int, str]:
        """Batch-fetch question titles by ID."""
        if not question_ids:
            return {}

        titles: dict[int, str] = {}
        # SO API accepts semicolon-separated IDs, max ~100 per request
        for i in range(0, len(question_ids), 100):
            batch = question_ids[i : i + 100]
            ids_str = ";".join(str(qid) for qid in batch)
            resp = await client.get(
                f"{_API_BASE}/questions/{ids_str}",
                params={"site": _DEFAULT_SITE},
            )
            resp.raise_for_status()
            data = resp.json()
            for q in data.get("items", []):
                titles[q["question_id"]] = unescape(q.get("title", ""))

        return titles
