"""Review generation via the backend structured review-prediction endpoint."""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_MAX_DIFF_CHARS = 8000


def _truncate_diff(diff: str) -> str:
    """Bound diff payload size before sending it to the backend."""
    if len(diff) <= _MAX_DIFF_CHARS:
        return diff
    return diff[:_MAX_DIFF_CHARS] + "\n\n... (diff truncated)"


def infer_delivery_context(pr_title: str, pr_body: str) -> str:
    """Infer the backend delivery context from PR metadata."""
    text = f"{pr_title}\n{pr_body}".lower()

    if any(keyword in text for keyword in ("incident", "sev", "outage", "postmortem")):
        return "incident"
    if any(keyword in text for keyword in ("hotfix", "fix-forward", "urgent fix")):
        return "hotfix"
    if any(keyword in text for keyword in ("exploratory", "prototype", "experiment", "spike", "poc")):
        return "exploratory"
    return "normal"


async def get_mini(username: str) -> dict | None:
    """Fetch a mini by username. Returns None if not found or not ready."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.minis_api_url}/api/minis/by-username/{quote(username, safe='')}",
                timeout=10.0,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "ready":
                return None
            return data
    except httpx.HTTPError as e:
        logger.error("Failed to fetch mini for %s: %s", username, e)
        return None


async def get_review_prediction(
    mini_id: str,
    *,
    repo_name: str | None,
    pr_title: str,
    pr_body: str,
    diff: str,
    changed_files: list[str] | None = None,
    author_model: str = "unknown",
    delivery_context: str = "normal",
) -> dict:
    """Fetch a structured review prediction from the backend."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.minis_api_url}/api/minis/{mini_id}/review-prediction",
                json={
                    "repo_name": repo_name,
                    "title": pr_title,
                    "description": pr_body or None,
                    "diff_summary": _truncate_diff(diff),
                    "changed_files": changed_files or [],
                    "author_model": author_model,
                    "delivery_context": delivery_context,
                },
                timeout=30.0,
            )
            if resp.status_code in {404, 405}:
                raise RuntimeError(
                    "Backend review-prediction endpoint is unavailable. "
                    "This GitHub app change depends on PR #55's published contract."
                )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        logger.error("Failed to fetch review prediction for mini %s: %s", mini_id, e)
        raise


def _format_prediction_comment(comment: dict) -> str:
    label = comment.get("type", "note").replace("_", " ").title()
    issue_key = comment.get("issue_key")
    if issue_key:
        label = f"{label} `{issue_key}`"

    summary = (comment.get("summary") or "").strip()
    rationale = (comment.get("rationale") or "").strip()

    parts = [f"**{label}**"]
    if summary:
        parts.append(summary)
    if rationale:
        parts.append(f"Why: {rationale}")
    return ": ".join([parts[0], " ".join(parts[1:])]) if len(parts) > 1 else parts[0]


def render_review_prediction(
    prediction: dict,
    *,
    requested_via_mention: bool = False,
    user_message: str = "",
) -> str:
    """Render the backend's structured review prediction as markdown."""
    feedback = prediction.get("expressed_feedback") or {}
    approval_state = (feedback.get("approval_state") or "uncertain").replace("_", " ")
    summary = (feedback.get("summary") or "").strip()
    comments = feedback.get("comments") or []

    lines: list[str] = []
    if requested_via_mention:
        if "review" not in user_message.lower():
            lines.append(
                "This integration currently returns a structured review prediction for the PR."
            )
            lines.append("")
        lines.append("Structured review prediction requested from the PR conversation.")
        lines.append("")

    lines.append(f"**Predicted stance:** `{approval_state}`")
    if summary:
        lines.append("")
        lines.append(summary)

    if comments:
        lines.append("")
        lines.append("**Key comments**")
        lines.append("")
        for comment in comments:
            lines.append(f"- {_format_prediction_comment(comment)}")
    elif approval_state == "approve":
        lines.append("")
        lines.append("No major blockers are predicted for this PR.")

    return "\n".join(lines)


async def generate_review(
    mini: dict,
    pr_title: str,
    pr_body: str,
    diff: str,
    *,
    repo_name: str | None = None,
    changed_files: list[str] | None = None,
    author_model: str = "unknown",
    delivery_context: str = "normal",
) -> str:
    """Generate a PR review using the backend review-prediction contract."""
    prediction = await get_review_prediction(
        mini["id"],
        repo_name=repo_name,
        pr_title=pr_title,
        pr_body=pr_body,
        diff=diff,
        changed_files=changed_files,
        author_model=author_model,
        delivery_context=delivery_context,
    )
    return render_review_prediction(prediction)


async def generate_mention_response(
    mini: dict,
    user_message: str,
    pr_title: str,
    pr_body: str,
    diff: str,
    *,
    repo_name: str | None = None,
    changed_files: list[str] | None = None,
    author_model: str = "unknown",
    delivery_context: str = "normal",
) -> str:
    """Generate a PR-thread response using the backend review-prediction contract."""
    prediction = await get_review_prediction(
        mini["id"],
        repo_name=repo_name,
        pr_title=pr_title,
        pr_body=pr_body,
        diff=diff,
        changed_files=changed_files,
        author_model=author_model,
        delivery_context=delivery_context,
    )
    return render_review_prediction(
        prediction,
        requested_via_mention=True,
        user_message=user_message,
    )


def format_review_comment(username: str, review_text: str) -> str:
    """Format a review with the mini's identity header."""
    return (
        f"### Review by @{username}'s mini\n\n"
        f"{review_text}\n\n"
        f"---\n"
        f"*This review was generated by [{username}'s mini](https://github.com/{username}) "
        f"using the Minis backend review-prediction API.*"
    )
