"""Trusted-service client for review-cycle prediction writeback."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

REVIEW_CYCLES_BASE_PATH = "/api/review-cycles/trusted/github"


def normalize_review_verdict(value: str | None) -> str:
    """Normalize GitHub review states to a small canonical verdict set."""
    if not value:
        return "unclear"

    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "approve": "approve",
        "approved": "approve",
        "comment": "comment",
        "commented": "comment",
        "request_changes": "request_changes",
        "changes_requested": "request_changes",
        "dismissed": "unclear",
        "pending": "unclear",
        "unclear": "unclear",
    }
    return mapping.get(normalized, "unclear")


def _trusted_headers() -> dict[str, str] | None:
    if not settings.trusted_service_secret:
        logger.warning(
            "TRUSTED_SERVICE_SECRET is not configured; skipping review-cycle writeback"
        )
        return None
    return {"X-Trusted-Service-Secret": settings.trusted_service_secret}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _post_writeback(path: str, payload: dict[str, Any]) -> bool:
    headers = _trusted_headers()
    if headers is None:
        return False

    url = f"{settings.minis_api_url}{path}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers=headers,
                json=payload,
                timeout=10.0,
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Review-cycle writeback failed with %s for %s: %s",
            exc.response.status_code,
            path,
            exc,
        )
        return False
    except httpx.HTTPError as exc:
        logger.warning("Review-cycle writeback failed for %s: %s", path, exc)
        return False

    return True


async def record_review_prediction(
    *,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    pr_title: str,
    pr_author_login: str | None,
    pr_html_url: str | None,
    reviewer_login: str,
    mini: dict[str, Any],
    predicted_review_body: str,
    github_review_id: int | None,
    github_review_state: str,
) -> bool:
    """Persist the latest app prediction for a reviewer on a PR."""
    payload = {
        "installation_id": installation_id,
        "repository": {
            "owner": owner,
            "name": repo,
        },
        "pull_request": {
            "number": pr_number,
            "title": pr_title,
            "author_login": pr_author_login,
            "html_url": pr_html_url,
        },
        "reviewer_login": reviewer_login,
        "predicted_review": {
            "github_review_id": github_review_id,
            "github_state": github_review_state,
            "verdict": normalize_review_verdict(github_review_state),
            "body": predicted_review_body,
            "submitted_at": _utc_now_iso(),
            "generator": {
                "kind": "minis_github_app",
                "model": settings.default_llm_model,
                "mini_id": mini.get("id"),
                "mini_username": mini.get("username") or reviewer_login,
            },
        },
    }
    return await _post_writeback(f"{REVIEW_CYCLES_BASE_PATH}/predictions", payload)


async def record_human_review_event(
    *,
    installation_id: int,
    owner: str,
    repo: str,
    pr_number: int,
    pr_title: str,
    pr_html_url: str | None,
    reviewer_login: str,
    action: str,
    review: dict[str, Any],
) -> bool:
    """Persist a human review webhook event against the latest prediction."""
    payload = {
        "installation_id": installation_id,
        "repository": {
            "owner": owner,
            "name": repo,
        },
        "pull_request": {
            "number": pr_number,
            "title": pr_title,
            "html_url": pr_html_url,
        },
        "reviewer_login": reviewer_login,
        "human_review": {
            "action": action,
            "github_review_id": review.get("id"),
            "github_state": review.get("state"),
            "verdict": normalize_review_verdict(review.get("state")),
            "body": review.get("body") or "",
            "submitted_at": review.get("submitted_at"),
            "html_url": review.get("html_url"),
            "commit_id": review.get("commit_id"),
            "author_association": review.get("author_association"),
            "captured_at": _utc_now_iso(),
        },
    }
    return await _post_writeback(
        f"{REVIEW_CYCLES_BASE_PATH}/human-review-events",
        payload,
    )
