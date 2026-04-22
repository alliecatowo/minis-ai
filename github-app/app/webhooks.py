"""Webhook event handlers for GitHub App events."""

from __future__ import annotations

import logging
import re

from app.config import settings
from app.github_api import (
    get_pr_details,
    get_pr_diff,
    get_pr_requested_reviewers,
    post_issue_comment,
    post_pr_review,
)
from app.review_cycles import record_human_review_event, record_review_prediction
from app.review import (
    format_review_comment,
    generate_mention_response,
    generate_review,
    get_mini,
)

logger = logging.getLogger(__name__)

# Pattern to match @mentions of minis: @username-mini
MENTION_PATTERN = re.compile(r"@(\w[\w-]*)" + re.escape(settings.mini_mention_suffix))


async def handle_pull_request_opened(payload: dict) -> None:
    """Handle pull_request.opened — auto-review if requested reviewers have minis."""
    pr = payload["pull_request"]
    repo = payload["repository"]
    installation_id = payload["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]
    pr_title = pr["title"]
    pr_body = pr.get("body") or ""
    pr_author_login = (pr.get("user") or {}).get("login")
    pr_html_url = pr.get("html_url")

    logger.info("PR #%d opened in %s/%s: %s", pr_number, owner, repo_name, pr_title)

    # Get requested reviewers
    reviewers = await get_pr_requested_reviewers(
        installation_id, owner, repo_name, pr_number
    )
    if not reviewers:
        logger.info("No requested reviewers for PR #%d, skipping", pr_number)
        return

    # Fetch diff
    diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)

    # Check which reviewers have minis and generate reviews
    for reviewer in reviewers:
        mini = await get_mini(reviewer)
        if not mini:
            logger.info("No mini found for reviewer %s", reviewer)
            continue

        logger.info("Generating review for PR #%d as %s's mini", pr_number, reviewer)

        review_text = await generate_review(
            mini=mini,
            pr_title=pr_title,
            pr_body=pr_body,
            diff=diff,
        )

        formatted = format_review_comment(reviewer, review_text)

        posted_review = await post_pr_review(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            pr_number=pr_number,
            body=formatted,
            event="COMMENT",
        )
        await record_review_prediction(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_author_login=pr_author_login,
            pr_html_url=pr_html_url,
            reviewer_login=reviewer,
            mini=mini,
            predicted_review_body=formatted,
            github_review_id=posted_review.get("id"),
            github_review_state=posted_review.get("state") or "COMMENTED",
        )

        logger.info("Posted review for PR #%d as %s's mini", pr_number, reviewer)


async def handle_issue_comment(payload: dict) -> None:
    """Handle issue_comment.created — check for @mentions of minis."""
    comment = payload["comment"]
    issue = payload["issue"]
    repo = payload["repository"]
    installation_id = payload["installation"]["id"]

    # Only handle PR comments (issues with pull_request key)
    if "pull_request" not in issue:
        return

    body = comment.get("body") or ""
    mentions = MENTION_PATTERN.findall(body)
    if not mentions:
        return

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = issue["number"]

    logger.info(
        "Comment on PR #%d mentions minis: %s",
        pr_number,
        ", ".join(mentions),
    )

    # Get PR details and diff
    pr_details = await get_pr_details(installation_id, owner, repo_name, pr_number)
    diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)

    for username in mentions:
        mini = await get_mini(username)
        if not mini:
            logger.info("No mini found for mentioned user %s", username)
            continue

        logger.info("Generating response for %s's mini on PR #%d", username, pr_number)

        response_text = await generate_mention_response(
            mini=mini,
            user_message=body,
            pr_title=pr_details["title"],
            pr_body=pr_details.get("body") or "",
            diff=diff,
        )

        formatted = format_review_comment(username, response_text)

        await post_issue_comment(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            issue_number=pr_number,
            body=formatted,
        )

        logger.info("Posted mention response for %s's mini on PR #%d", username, pr_number)


async def handle_pr_review_comment(payload: dict) -> None:
    """Handle pull_request_review_comment.created — respond to review threads mentioning minis."""
    comment = payload["comment"]
    pr = payload["pull_request"]
    repo = payload["repository"]
    installation_id = payload["installation"]["id"]

    body = comment.get("body") or ""
    mentions = MENTION_PATTERN.findall(body)
    if not mentions:
        return

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]

    logger.info(
        "Review comment on PR #%d mentions minis: %s",
        pr_number,
        ", ".join(mentions),
    )

    diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)

    for username in mentions:
        mini = await get_mini(username)
        if not mini:
            continue

        response_text = await generate_mention_response(
            mini=mini,
            user_message=body,
            pr_title=pr["title"],
            pr_body=pr.get("body") or "",
            diff=diff,
        )

        formatted = format_review_comment(username, response_text)

        # Reply as an issue comment (review comment replies require different API)
        await post_issue_comment(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            issue_number=pr_number,
            body=formatted,
        )

        logger.info("Posted review thread response for %s's mini on PR #%d", username, pr_number)


async def handle_pull_request_review(payload: dict) -> None:
    """Handle pull_request_review webhooks to persist human review outcomes."""
    review = payload["review"]
    pr = payload["pull_request"]
    repo = payload["repository"]
    installation_id = payload["installation"]["id"]
    action = payload.get("action", "")

    reviewer = review.get("user") or payload.get("sender") or {}
    reviewer_login = reviewer.get("login")
    reviewer_type = reviewer.get("type")

    if not reviewer_login:
        logger.info("Skipping pull_request_review without reviewer login")
        return

    if reviewer_type and reviewer_type != "User":
        logger.info(
            "Skipping non-human pull_request_review on PR #%d from %s (%s)",
            pr["number"],
            reviewer_login,
            reviewer_type,
        )
        return

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]

    await record_human_review_event(
        installation_id=installation_id,
        owner=owner,
        repo=repo_name,
        pr_number=pr_number,
        pr_title=pr["title"],
        pr_html_url=pr.get("html_url"),
        reviewer_login=reviewer_login,
        action=action,
        review=review,
    )

    logger.info(
        "Recorded human review event %s for PR #%d from %s",
        action,
        pr_number,
        reviewer_login,
    )
