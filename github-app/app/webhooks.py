"""Webhook event handlers for GitHub App events."""

from __future__ import annotations

import logging
import re

from app.config import settings
from app.github_api import (
    get_pr_changed_files,
    get_pr_details,
    get_pr_diff,
    get_pr_requested_reviewers,
    get_repo_collaborator_permission,
    post_issue_comment,
    post_pr_review,
)
from app.review import (
    format_review_comment,
    generate_mention_response,
    get_mini,
    get_review_prediction,
    infer_author_model_from_github_context,
    infer_delivery_context,
    render_review_prediction,
)
from app.review_cycles import record_human_review_outcome, record_review_prediction

logger = logging.getLogger(__name__)

# Pattern to match @mentions of minis: @username-mini
MENTION_PATTERN = re.compile(r"@(\w[\w-]*)" + re.escape(settings.mini_mention_suffix))


def _pr_author_context(pr: dict) -> tuple[str | None, str | None]:
    author = pr.get("user") or {}
    author_login = author.get("login")
    author_association = pr.get("author_association")
    return author_login, author_association


async def _get_permission_hint(
    installation_id: int,
    owner: str,
    repo_name: str,
    login: str | None,
) -> str | None:
    if not login:
        return None

    try:
        return await get_repo_collaborator_permission(installation_id, owner, repo_name, login)
    except Exception:
        logger.warning(
            "Failed to fetch collaborator permission for %s in %s/%s",
            login,
            owner,
            repo_name,
        )
        return None


async def _infer_author_model_for_reviewer(
    *,
    installation_id: int,
    owner: str,
    repo_name: str,
    author_login: str | None,
    author_association: str | None,
    reviewer_login: str,
    author_permission: str | None = None,
) -> str:
    reviewer_permission = None
    normalized_author = (author_login or "").strip().lower()
    normalized_reviewer = reviewer_login.strip().lower()

    if normalized_reviewer and normalized_reviewer != normalized_author:
        reviewer_permission = await _get_permission_hint(
            installation_id,
            owner,
            repo_name,
            reviewer_login,
        )

    return infer_author_model_from_github_context(
        author_association=author_association,
        author_login=author_login,
        repo_owner_login=owner,
        reviewer_login=reviewer_login,
        author_permission=author_permission,
        reviewer_permission=reviewer_permission,
    )


async def _resolve_requested_reviewers(
    payload: dict,
    *,
    installation_id: int,
    owner: str,
    repo_name: str,
    pr_number: int,
) -> list[dict[str, str | bool | None]]:
    requested_reviewer = payload.get("requested_reviewer") or {}
    requested_login = requested_reviewer.get("login")
    requested_type = requested_reviewer.get("type")
    if (
        payload.get("action") == "review_requested"
        and requested_login
        and (requested_type is None or requested_type == "User")
    ):
        return [
            {
                "login": requested_login,
                "type": requested_type,
                "site_admin": bool(requested_reviewer.get("site_admin", False)),
            }
        ]

    return await get_pr_requested_reviewers(installation_id, owner, repo_name, pr_number)


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
    pr_html_url = pr.get("html_url")
    repo_full_name = f"{owner}/{repo_name}"
    delivery_context = infer_delivery_context(pr_title, pr_body)
    author_login, author_association = _pr_author_context(pr)

    logger.info("PR #%d opened in %s/%s: %s", pr_number, owner, repo_name, pr_title)

    reviewers = await _resolve_requested_reviewers(
        payload,
        installation_id=installation_id,
        owner=owner,
        repo_name=repo_name,
        pr_number=pr_number,
    )
    if not reviewers:
        logger.info("No requested reviewers for PR #%d, skipping", pr_number)
        return

    diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)
    changed_files = await get_pr_changed_files(installation_id, owner, repo_name, pr_number)
    author_permission = await _get_permission_hint(installation_id, owner, repo_name, author_login)

    for reviewer in reviewers:
        reviewer_login = reviewer["login"]
        if not reviewer_login:
            continue

        mini = await get_mini(reviewer_login)
        if not mini:
            logger.info("No mini found for reviewer %s", reviewer_login)
            continue

        author_model = await _infer_author_model_for_reviewer(
            installation_id=installation_id,
            owner=owner,
            repo_name=repo_name,
            author_login=author_login,
            author_association=author_association,
            reviewer_login=reviewer_login,
            author_permission=author_permission,
        )
        prediction = await get_review_prediction(
            mini["id"],
            repo_name=repo_full_name,
            pr_title=pr_title,
            pr_body=pr_body,
            diff=diff,
            changed_files=changed_files,
            author_model=author_model,
            delivery_context=delivery_context,
        )
        review_text = render_review_prediction(prediction)

        logger.info("Generating review for PR #%d as %s's mini", pr_number, reviewer_login)

        formatted = format_review_comment(reviewer_login, review_text)
        posted_review = await post_pr_review(
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            pr_number=pr_number,
            body=formatted,
            event="COMMENT",
        )
        persisted = await record_review_prediction(
            mini_id=mini["id"],
            installation_id=installation_id,
            owner=owner,
            repo=repo_name,
            pr_number=pr_number,
            pr_title=pr_title,
            pr_html_url=pr_html_url,
            reviewer_login=reviewer_login,
            prediction=prediction,
            github_review_id=posted_review.get("id"),
            github_review_state=posted_review.get("state"),
            author_login=author_login,
            author_association=author_association,
        )

        if persisted:
            logger.info("Posted review for PR #%d as %s's mini", pr_number, reviewer_login)
        else:
            logger.warning(
                "Posted review for PR #%d as %s's mini, but review-cycle writeback failed",
                pr_number,
                reviewer_login,
            )


async def handle_issue_comment(payload: dict) -> None:
    """Handle issue_comment.created — check for @mentions of minis."""
    comment = payload["comment"]
    issue = payload["issue"]
    repo = payload["repository"]
    installation_id = payload["installation"]["id"]

    if "pull_request" not in issue:
        return

    body = comment.get("body") or ""
    mentions = MENTION_PATTERN.findall(body)
    if not mentions:
        return

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = issue["number"]
    repo_full_name = f"{owner}/{repo_name}"

    logger.info("Comment on PR #%d mentions minis: %s", pr_number, ", ".join(mentions))

    pr_details = await get_pr_details(installation_id, owner, repo_name, pr_number)
    diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)
    changed_files = await get_pr_changed_files(installation_id, owner, repo_name, pr_number)
    delivery_context = infer_delivery_context(pr_details["title"], pr_details.get("body") or "")
    author_login, author_association = _pr_author_context(pr_details)
    author_permission = await _get_permission_hint(installation_id, owner, repo_name, author_login)

    for username in mentions:
        mini = await get_mini(username)
        if not mini:
            logger.info("No mini found for mentioned user %s", username)
            continue

        author_model = await _infer_author_model_for_reviewer(
            installation_id=installation_id,
            owner=owner,
            repo_name=repo_name,
            author_login=author_login,
            author_association=author_association,
            reviewer_login=username,
            author_permission=author_permission,
        )
        logger.info("Generating response for %s's mini on PR #%d", username, pr_number)

        response_text = await generate_mention_response(
            mini=mini,
            user_message=body,
            pr_title=pr_details["title"],
            pr_body=pr_details.get("body") or "",
            diff=diff,
            repo_name=repo_full_name,
            changed_files=changed_files,
            author_model=author_model,
            delivery_context=delivery_context,
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
    repo_full_name = f"{owner}/{repo_name}"

    logger.info("Review comment on PR #%d mentions minis: %s", pr_number, ", ".join(mentions))

    diff = await get_pr_diff(installation_id, owner, repo_name, pr_number)
    changed_files = await get_pr_changed_files(installation_id, owner, repo_name, pr_number)
    delivery_context = infer_delivery_context(pr["title"], pr.get("body") or "")
    author_login, author_association = _pr_author_context(pr)
    author_permission = await _get_permission_hint(installation_id, owner, repo_name, author_login)

    for username in mentions:
        mini = await get_mini(username)
        if not mini:
            continue

        author_model = await _infer_author_model_for_reviewer(
            installation_id=installation_id,
            owner=owner,
            repo_name=repo_name,
            author_login=author_login,
            author_association=author_association,
            reviewer_login=username,
            author_permission=author_permission,
        )
        response_text = await generate_mention_response(
            mini=mini,
            user_message=body,
            pr_title=pr["title"],
            pr_body=pr.get("body") or "",
            diff=diff,
            repo_name=repo_full_name,
            changed_files=changed_files,
            author_model=author_model,
            delivery_context=delivery_context,
        )

        formatted = format_review_comment(username, response_text)

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

    mini = await get_mini(reviewer_login)
    if not mini:
        logger.info("No mini found for reviewer %s; skipping review-cycle writeback", reviewer_login)
        return

    persisted = await record_human_review_outcome(
        mini_id=mini["id"],
        owner=repo["owner"]["login"],
        repo=repo["name"],
        pr_number=pr["number"],
        reviewer_login=reviewer_login,
        action=action,
        review=review,
    )

    if persisted:
        logger.info(
            "Recorded human review event %s for PR #%d from %s",
            action,
            pr["number"],
            reviewer_login,
        )
    else:
        logger.warning(
            "Failed to persist human review event %s for PR #%d from %s",
            action,
            pr["number"],
            reviewer_login,
        )
