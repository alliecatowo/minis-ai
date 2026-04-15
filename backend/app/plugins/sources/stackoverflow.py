"""Stack Overflow ingestion source plugin — fetches top answers for personality analysis."""

from __future__ import annotations

import asyncio
import logging
import re
from html import unescape
from typing import Any

import httpx

from app.plugins.base import IngestionResult, IngestionSource

logger = logging.getLogger(__name__)

_API_BASE = "https://api.stackexchange.com/2.3"
_DEFAULT_SITE = "stackoverflow"
_PAGE_SIZE = 50  # fetch 50 answers per request


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities to plain text."""
    text = re.sub(r"<[^>]+>", "", html)
    return unescape(text).strip()


class StackOverflowSource(IngestionSource):
    """Ingestion source that fetches Stack Overflow answers for a user."""

    name = "stackoverflow"

    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch SO answers (with question body + answer comments) and format as evidence.

        Fetches up to 50 top-voted answers, the full question text for each answer
        (for context), and comments on answers (which reveal communication style and
        how the user defends/refines their answers).

        Args:
            identifier: Stack Overflow numeric user ID or display name.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            user_id = await self._resolve_user_id(client, identifier)
            user_info = await self._fetch_user_info(client, user_id)
            answers = await self._fetch_top_answers(client, user_id)

        evidence = self._format_evidence(answers, user_info)

        return IngestionResult(
            source_name=self.name,
            identifier=identifier,
            evidence=evidence,
            raw_data={
                "user_id": user_id,
                "user_info": user_info,
                "answers_count": len(answers),
            },
            stats={
                "answers_fetched": len(answers),
                "total_score": sum(a.get("score", 0) for a in answers),
                "accepted_count": sum(1 for a in answers if a.get("is_accepted")),
                "evidence_length": len(evidence),
            },
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
            raise ValueError(
                f"No Stack Overflow user found matching '{identifier}'"
            )

        # Prefer exact display_name match (case-insensitive), fall back to top result
        for user in items:
            if user.get("display_name", "").lower() == identifier.lower():
                return user["user_id"]
        return items[0]["user_id"]

    async def _fetch_user_info(self, client: httpx.AsyncClient, user_id: int) -> dict:
        """Fetch basic user profile info."""
        resp = await client.get(
            f"{_API_BASE}/users/{user_id}",
            params={"site": _DEFAULT_SITE},
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        return items[0] if items else {}

    async def _fetch_top_answers(
        self, client: httpx.AsyncClient, user_id: int
    ) -> list[dict]:
        """Fetch top-voted answers with full body text, question body, and answer comments."""
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

        if not answers:
            return answers

        # Batch-fetch question details (title + body) and answer comments in parallel
        question_ids = [a["question_id"] for a in answers if "question_id" in a]
        answer_ids = [a["answer_id"] for a in answers if "answer_id" in a]

        questions_detail, comments_by_answer = await asyncio.gather(
            self._fetch_question_details(client, question_ids),
            self._fetch_answer_comments(client, answer_ids),
        )

        for answer in answers:
            qid = answer.get("question_id")
            aid = answer.get("answer_id")
            q_detail = questions_detail.get(qid, {})
            answer["_question_title"] = q_detail.get("title", "Unknown Question")
            answer["_question_body"] = q_detail.get("body", "")
            answer["_comments"] = comments_by_answer.get(aid, [])

        return answers

    async def _fetch_question_details(
        self, client: httpx.AsyncClient, question_ids: list[int]
    ) -> dict[int, dict]:
        """Batch-fetch question title + body by ID."""
        if not question_ids:
            return {}

        questions: dict[int, dict] = {}
        # SO API accepts semicolon-separated IDs, max ~100 per request
        for i in range(0, len(question_ids), 100):
            batch = question_ids[i : i + 100]
            ids_str = ";".join(str(qid) for qid in batch)
            try:
                resp = await client.get(
                    f"{_API_BASE}/questions/{ids_str}",
                    params={"site": _DEFAULT_SITE, "filter": "withbody"},
                )
                resp.raise_for_status()
                data = resp.json()
                for q in data.get("items", []):
                    body_html = q.get("body", "")
                    body_text = _strip_html(body_html)
                    questions[q["question_id"]] = {
                        "title": unescape(q.get("title", "")),
                        "body": body_text[:600] + "..." if len(body_text) > 600 else body_text,
                    }
            except httpx.HTTPError as exc:
                logger.warning("Failed to fetch SO question details: %s", exc)

        return questions

    async def _fetch_answer_comments(
        self, client: httpx.AsyncClient, answer_ids: list[int]
    ) -> dict[int, list[dict]]:
        """Batch-fetch comments for answers.

        Comments on answers often contain follow-up Q&A and clarifications
        that reveal the answerer's communication style and willingness to help.
        """
        if not answer_ids:
            return {}

        comments_by_answer: dict[int, list[dict]] = {}
        # SO API accepts semicolon-separated IDs, max ~100 per request
        for i in range(0, len(answer_ids), 100):
            batch = answer_ids[i : i + 100]
            ids_str = ";".join(str(aid) for aid in batch)
            try:
                resp = await client.get(
                    f"{_API_BASE}/answers/{ids_str}/comments",
                    params={
                        "site": _DEFAULT_SITE,
                        "order": "asc",
                        "sort": "creation",
                        "pagesize": 10,  # max 10 comments per answer
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                for comment in data.get("items", []):
                    aid = comment.get("post_id")
                    if aid:
                        comments_by_answer.setdefault(aid, []).append(comment)
            except httpx.HTTPError as exc:
                logger.warning("Failed to fetch SO answer comments: %s", exc)

        return comments_by_answer

    def _format_evidence(self, answers: list[dict], user_info: dict) -> str:
        """Format answers (with question context and comments) into evidence text."""
        display_name = user_info.get("display_name", "Unknown")
        reputation = user_info.get("reputation", 0)

        lines = [
            "## Stack Overflow Answers",
            f"User: {display_name} (Reputation: {reputation:,})",
            "",
            "(SO answers reveal expertise areas, teaching/explanation style, and technical",
            "depth. High-voted answers indicate recognized knowledge. Comments on answers",
            "reveal follow-up communication style and how the person engages with questioners.)",
            "",
        ]

        # Collect all tags for a summary
        all_tags: dict[str, int] = {}

        for answer in answers:
            title = answer.get("_question_title", "Unknown Question")
            question_body = answer.get("_question_body", "")
            comments = answer.get("_comments", [])
            tags = answer.get("tags", [])
            score = answer.get("score", 0)
            accepted = answer.get("is_accepted", False)
            body_html = answer.get("body", "")
            body_text = _strip_html(body_html)

            for tag in tags:
                all_tags[tag] = all_tags.get(tag, 0) + 1

            tag_str = ", ".join(tags) if tags else "untagged"
            status = f"Score: {score}"
            if accepted:
                status += ", Accepted"

            # Truncate very long answers to keep evidence manageable
            if len(body_text) > 800:
                body_text = body_text[:800] + "..."

            lines.append(f'### Answer to: "{title}" [{tag_str}] ({status})')

            # Include abbreviated question body for context
            if question_body:
                q_excerpt = question_body[:300] + "..." if len(question_body) > 300 else question_body
                lines.append(f"*Question:* {q_excerpt}")

            lines.append(f'> "{body_text}"')

            # Include answer comments (conversations that show communication style)
            if comments:
                lines.append("*Comments on this answer:*")
                for comment in comments[:5]:  # cap at 5 comments per answer
                    comment_body = _strip_html(comment.get("body", ""))
                    if not comment_body:
                        continue
                    comment_score = comment.get("score", 0)
                    comment_owner = comment.get("owner", {}).get("display_name", "")
                    owner_str = f"[{comment_owner}]" if comment_owner else ""
                    score_str = f" ({comment_score} votes)" if comment_score else ""
                    if len(comment_body) > 300:
                        comment_body = comment_body[:300] + "..."
                    lines.append(f'  - {owner_str}{score_str} "{comment_body}"')

            lines.append("")

        # Add tag expertise summary
        if all_tags:
            sorted_tags = sorted(all_tags.items(), key=lambda x: x[1], reverse=True)
            top_tags = [f"{tag} ({count})" for tag, count in sorted_tags[:15]]
            lines.insert(3, f"Top tags: {', '.join(top_tags)}")
            lines.insert(4, "")

        return "\n".join(lines)
