"""Review generation via the backend structured review-prediction contract."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_MAX_DIFF_CHARS = 8000
_AUTHOR_ASSOCIATION_TO_MODEL = {
    "OWNER": "senior_peer",
    "MEMBER": "senior_peer",
    "COLLABORATOR": "trusted_peer",
    "CONTRIBUTOR": "trusted_peer",
    "FIRST_TIME_CONTRIBUTOR": "junior_peer",
    "FIRST_TIMER": "junior_peer",
}
_PERMISSION_TO_RANK = {
    "none": 0,
    "read": 1,
    "triage": 2,
    "write": 3,
    "maintain": 4,
    "admin": 5,
}


def _trusted_headers() -> dict[str, str] | None:
    if not settings.trusted_service_secret:
        logger.error("TRUSTED_SERVICE_SECRET is not configured")
        return None
    return {"X-Trusted-Service-Secret": settings.trusted_service_secret}


def _truncate_diff(diff: str) -> str:
    """Bound diff payload size before sending it to the backend."""
    if len(diff) <= _MAX_DIFF_CHARS:
        return diff
    return diff[:_MAX_DIFF_CHARS] + "\n\n... (diff truncated)"


def infer_delivery_context(pr_title: str, pr_body: str) -> str:
    """Infer the review-delivery context from PR metadata."""
    text = f"{pr_title}\n{pr_body}".lower()

    if any(keyword in text for keyword in ("incident", "sev", "outage", "postmortem")):
        return "incident"
    if any(keyword in text for keyword in ("hotfix", "fix-forward", "urgent fix")):
        return "hotfix"
    if any(
        keyword in text for keyword in ("exploratory", "prototype", "experiment", "spike", "poc")
    ):
        return "exploratory"
    return "normal"


def infer_author_model_from_github_context(
    *,
    author_association: str | None,
    author_login: str | None = None,
    repo_owner_login: str | None = None,
    reviewer_login: str | None = None,
    author_permission: str | None = None,
    reviewer_permission: str | None = None,
) -> str:
    """Map GitHub PR author context onto the backend's coarse author model."""
    normalized_author = (author_login or "").strip().lower()
    normalized_owner = (repo_owner_login or "").strip().lower()
    normalized_reviewer = (reviewer_login or "").strip().lower()

    if normalized_author and normalized_reviewer and normalized_author == normalized_reviewer:
        return "trusted_peer"

    if normalized_author and normalized_owner and normalized_author == normalized_owner:
        return "senior_peer"

    author_rank = _PERMISSION_TO_RANK.get((author_permission or "").strip().lower())
    reviewer_rank = _PERMISSION_TO_RANK.get((reviewer_permission or "").strip().lower())
    if author_rank is not None and reviewer_rank is not None:
        if author_rank > reviewer_rank:
            return "senior_peer"
        if author_rank < reviewer_rank:
            return "junior_peer"
        if author_rank >= _PERMISSION_TO_RANK["write"]:
            return "trusted_peer"

    normalized_association = (author_association or "").strip().upper()
    inferred = _AUTHOR_ASSOCIATION_TO_MODEL.get(normalized_association)
    if inferred:
        return inferred

    return "unknown"


async def get_mini(username: str) -> dict | None:
    """Fetch a mini from the trusted Minis backend route."""
    headers = _trusted_headers()
    if headers is None:
        return None

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.minis_api_url}/api/minis/trusted/by-username/{quote(username, safe='')}",
                headers=headers,
                timeout=10.0,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "ready":
                return None
            return data
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch mini for %s: %s", username, exc)
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
) -> dict[str, Any]:
    """Fetch a structured review prediction from the trusted backend route."""
    headers = _trusted_headers()
    if headers is None:
        raise RuntimeError("TRUSTED_SERVICE_SECRET is required for review prediction")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.minis_api_url}/api/minis/trusted/{mini_id}/review-prediction",
                headers=headers,
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
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch review prediction for mini %s: %s", mini_id, exc)
        raise


def _format_prediction_comment(
    comment: dict[str, Any],
    *,
    framework_id: str | None = None,
    revision: int | None = None,
) -> str:
    label = str(comment.get("type", "note")).replace("_", " ").title()
    issue_key = comment.get("issue_key")
    if issue_key:
        label = f"{label} `{issue_key}`"

    summary = str(comment.get("summary") or "").strip()
    rationale = str(comment.get("rationale") or "").strip()

    parts = [f"**{label}**"]
    if summary:
        parts.append(summary)
    if rationale:
        parts.append(f"Why: {rationale}")

    formatted = ": ".join([parts[0], " ".join(parts[1:])]) if len(parts) > 1 else parts[0]

    if framework_id:
        if isinstance(revision, int) and revision > 0:
            attribution = f"[from framework: {framework_id}, validated {revision}×]"
        else:
            attribution = f"[from framework: {framework_id}]"
        formatted = f"{formatted} {attribution}"

    return formatted


def _format_inline_prediction_comment(
    comment: dict[str, Any],
    *,
    framework_id: str | None = None,
    revision: int | None = None,
) -> str:
    body = _format_prediction_comment(
        comment,
        framework_id=framework_id,
        revision=revision,
    )
    suggested_replacement = _prediction_comment_suggested_replacement(comment)
    if suggested_replacement:
        body = f"{body}\n\n```suggestion\n{suggested_replacement}\n```"
    return body


def _prediction_comment_suggested_replacement(comment: dict[str, Any]) -> str | None:
    """Return explicit suggestion text from the prediction artifact, if present."""
    for key in ("suggested_replacement", "suggestion"):
        value = comment.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip("\n")
    return None


_MAX_FRAMEWORK_SIGNALS = 5


def _render_framework_footer(prediction: dict[str, Any]) -> str:
    """Render a compact 'Framework signals' footer from decision-framework metadata.

    Reads ``prediction["framework_signals"]`` — a list of dicts with keys:
      - ``name`` (str): human-readable framework label
      - ``confidence`` (float 0–1): learned confidence for this framework
      - ``revision_count`` (int): number of review outcomes that shaped it

    Returns an empty string when the field is absent or empty.
    """
    signals = prediction.get("framework_signals")
    if not signals:
        return ""

    # Sort by confidence descending, cap at top N
    sorted_signals = sorted(
        [signal for signal in signals if isinstance(signal, dict)],
        key=lambda signal: _safe_float(signal.get("confidence"), default=0.0),
        reverse=True,
    )
    top = sorted_signals[:_MAX_FRAMEWORK_SIGNALS]

    parts: list[str] = []
    for sig in top:
        name = str(sig.get("name") or "unknown").strip()
        confidence = _safe_float(sig.get("confidence"), default=0.5)
        revision_count = _safe_int(sig.get("revision_count"))

        if confidence > 0.7:
            badge = "[HIGH CONFIDENCE ✓]"
        elif confidence < 0.3:
            badge = "[LOW CONFIDENCE ⚠]"
        else:
            badge = ""

        validated = (
            f"[validated {revision_count} time{'s' if revision_count != 1 else ''}]"
            if revision_count > 0
            else ""
        )

        confidence_label = f"[confidence {confidence:.0%}]"
        tokens = [f"- **{name}**", confidence_label, badge, validated]
        parts.append(" ".join(t for t in tokens if t))

    if not parts:
        return ""

    lines = ["", "---", "**Framework signals**", ""]
    lines.extend(parts)
    return "\n".join(lines)


def _safe_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _build_signal_index(prediction: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a {key: signal} lookup from all private_assessment signal lists.

    Used to look up framework_id / revision when rendering expressed_feedback
    comments that reference a matching issue_key.
    """
    index: dict[str, dict[str, Any]] = {}
    assessment = prediction.get("private_assessment") or {}
    for bucket in ("blocking_issues", "non_blocking_issues", "open_questions", "positive_signals"):
        for signal in assessment.get(bucket) or []:
            if isinstance(signal, dict):
                key = signal.get("key")
                if key:
                    index[str(key)] = signal
    return index


def build_inline_review_comments(
    prediction: dict[str, Any],
    *,
    reviewer_login: str,
    changed_files: list[str] | None = None,
    diff: str | None = None,
) -> list[dict[str, Any]]:
    """Build GitHub inline comments from prediction location metadata.

    For comments that supply an explicit ``path`` and ``line``, these are used
    directly.  For comments without explicit location, a heuristic is applied:

    1. If the comment text mentions a filename from ``changed_files``, the comment
       is attached to line 1 of that file (RIGHT side).
    2. If no file match is found, the comment is skipped (it will appear in the
       top-level review body instead).

    Replacement text (``suggestion`` / ``suggested_replacement``) is always taken
    verbatim from the prediction artifact — it is never inferred from the diff.
    """
    if _review_prediction_unavailable_reason(prediction):
        return []

    feedback = prediction.get("expressed_feedback") or {}
    comments = feedback.get("comments") or []
    if not isinstance(comments, list):
        return []

    signal_index = _build_signal_index(prediction)
    inline_comments: list[dict[str, Any]] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue

        github_comment = _build_github_inline_comment(
            comment,
            signal_index=signal_index,
            reviewer_login=reviewer_login,
        )
        if github_comment:
            inline_comments.append(github_comment)
            continue

        # Heuristic fallback: try to map to a changed file by name mention (MINI-46)
        if changed_files:
            heuristic_comment = _build_heuristic_inline_comment(
                comment,
                signal_index=signal_index,
                reviewer_login=reviewer_login,
                changed_files=changed_files,
            )
            if heuristic_comment:
                inline_comments.append(heuristic_comment)

    return inline_comments


def _build_heuristic_inline_comment(
    comment: dict[str, Any],
    *,
    signal_index: dict[str, dict[str, Any]],
    reviewer_login: str,
    changed_files: list[str],
) -> dict[str, Any] | None:
    """Attach a comment to line 1 of the first changed file mentioned in its text.

    This heuristic fires only when the prediction omits explicit path/line data.
    We look for bare filenames or path basenames in the comment text.
    """
    comment_text = " ".join(
        str(v) for v in [comment.get("summary"), comment.get("rationale")] if v
    ).lower()
    if not comment_text.strip():
        return None

    matched_path: str | None = None
    for file_path in changed_files:
        basename = file_path.rsplit("/", 1)[-1].lower()
        # Match on full path or just the basename
        if file_path.lower() in comment_text or basename in comment_text:
            matched_path = file_path
            break

    if not matched_path:
        return None

    issue_key = comment.get("issue_key")
    matched_signal = signal_index.get(str(issue_key)) if issue_key else None
    framework_id: str | None = None
    revision: int | None = None
    if matched_signal:
        framework_id = matched_signal.get("framework_id")
        revision = matched_signal.get("revision")

    return {
        "path": matched_path,
        "line": 1,
        "side": "RIGHT",
        "body": format_review_comment(
            reviewer_login,
            _format_inline_prediction_comment(
                comment,
                framework_id=framework_id,
                revision=revision,
            ),
        ),
    }


def _build_github_inline_comment(
    comment: dict[str, Any],
    *,
    signal_index: dict[str, dict[str, Any]],
    reviewer_login: str,
) -> dict[str, Any] | None:
    path = comment.get("path")
    line = _safe_int(comment.get("line"))
    if not isinstance(path, str) or not path.strip() or line <= 0:
        return None

    issue_key = comment.get("issue_key")
    matched_signal = signal_index.get(str(issue_key)) if issue_key else None
    framework_id: str | None = None
    revision: int | None = None
    if matched_signal:
        framework_id = matched_signal.get("framework_id")
        revision = matched_signal.get("revision")

    github_comment: dict[str, Any] = {
        "path": path.strip(),
        "line": line,
        "side": _normalize_github_side(comment.get("side")),
        "body": format_review_comment(
            reviewer_login,
            _format_inline_prediction_comment(
                comment,
                framework_id=framework_id,
                revision=revision,
            ),
        ),
    }

    start_line = _safe_int(comment.get("start_line"))
    if start_line > 0 and start_line != line:
        github_comment["start_line"] = start_line
        github_comment["start_side"] = _normalize_github_side(
            comment.get("start_side") or comment.get("side")
        )

    return github_comment


def _normalize_github_side(value: Any) -> str:
    side = str(value or "RIGHT").strip().upper()
    return side if side in {"LEFT", "RIGHT"} else "RIGHT"


def _review_prediction_unavailable_reason(prediction: dict[str, Any]) -> str | None:
    required = {"prediction_available", "mode", "unavailable_reason"}
    if not required.issubset(prediction):
        return "backend response omitted review prediction availability contract"

    if prediction.get("prediction_available") is False or prediction.get("mode") == "gated":
        return str(prediction.get("unavailable_reason") or "review prediction is gated")

    if prediction.get("prediction_available") is not True:
        return "backend response returned invalid prediction_available value"
    if prediction.get("mode") != "llm":
        return f"backend response returned unsupported review prediction mode: {prediction.get('mode')}"
    if prediction.get("unavailable_reason") is not None:
        return "backend response returned unavailable_reason for available prediction"
    return None


def render_review_prediction(
    prediction: dict[str, Any],
    *,
    requested_via_mention: bool = False,
    requested_via_review_request: bool = False,
    user_message: str = "",
) -> str:
    """Render the backend's structured review prediction as markdown."""
    unavailable_reason = _review_prediction_unavailable_reason(prediction)
    if unavailable_reason:
        reason = unavailable_reason.strip()
        mode = "gated"
        lines = ["**Review prediction unavailable**"]
        if requested_via_review_request:
            lines.extend(
                [
                    "",
                    "Reviewer mode was requested for this PR, but Minis cannot produce a structured prediction yet.",
                ]
            )
        lines.extend(["", f"**Mode:** `{mode}`", f"**Reason:** {reason}"])
        if requested_via_mention:
            lines.insert(0, "Structured review prediction requested from the PR conversation.")
            lines.insert(1, "")
        return "\n".join(lines)

    feedback = prediction.get("expressed_feedback") or {}
    approval_state = str(feedback.get("approval_state") or "uncertain").replace("_", " ")
    summary = str(feedback.get("summary") or "").strip()
    comments = feedback.get("comments") or []

    # Build signal index for framework attribution look-up
    signal_index = _build_signal_index(prediction)

    lines: list[str] = []
    if requested_via_mention:
        if "review" not in user_message.lower():
            lines.append(
                "This integration currently returns a structured review prediction for the PR."
            )
            lines.append("")
        lines.append("Structured review prediction requested from the PR conversation.")
        lines.append("")
    elif requested_via_review_request:
        lines.append("Reviewer mode: structured prediction for the requested reviewer.")
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
            issue_key = comment.get("issue_key") if isinstance(comment, dict) else None
            matched_signal = signal_index.get(str(issue_key)) if issue_key else None
            framework_id: str | None = None
            revision: int | None = None
            if matched_signal:
                framework_id = matched_signal.get("framework_id")
                revision = matched_signal.get("revision")
            lines.append(
                f"- {_format_prediction_comment(comment, framework_id=framework_id, revision=revision)}"
            )
    elif approval_state == "approve":
        lines.append("")
        lines.append("No major blockers are predicted for this PR.")

    footer = _render_framework_footer(prediction)
    if footer:
        lines.append(footer)

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
