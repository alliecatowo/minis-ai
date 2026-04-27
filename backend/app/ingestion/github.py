"""GitHub API client for fetching user activity data."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.ingestion.github_http import gh_request

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, using default %d", name, raw, default)
        return default
    if value < minimum:
        logger.warning("%s must be >= %d, using default %d", name, minimum, default)
        return default
    return value


def _env_optional_int(name: str, default: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r, using default %r", name, raw, default)
        return default
    if value <= 0:
        return None
    return value


GITHUB_MAX_PRS = _env_int("GITHUB_MAX_PRS", 1000)
GITHUB_MAX_COMMITS = _env_int("GITHUB_MAX_COMMITS", 2000)
GITHUB_MAX_ISSUES = _env_int("GITHUB_MAX_ISSUES", 1000)
GITHUB_MAX_REPOS = _env_int("GITHUB_MAX_REPOS", 1000)
GITHUB_MAX_REPOS_WITH_LANGUAGES = _env_int("GITHUB_MAX_REPOS_WITH_LANGUAGES", 1000)
GITHUB_MAX_REVIEW_COMMENTS_PER_PR = _env_optional_int("GITHUB_MAX_REVIEW_COMMENTS_PER_PR", None)
GITHUB_MAX_ISSUE_COMMENTS_PER_PR = _env_optional_int("GITHUB_MAX_ISSUE_COMMENTS_PER_PR", None)
GITHUB_MAX_REVIEWS_AUTHORED = max(1, int(settings.github_max_reviews_authored))
GITHUB_MAX_INLINE_COMMENTS = max(1, int(settings.github_max_inline_comments))
GITHUB_MAX_STARRED = max(1, int(settings.github_max_starred))
GITHUB_MAX_WATCHED = max(1, int(settings.github_max_watched))
GITHUB_MAX_GISTS = max(1, int(settings.github_max_gists))
GITHUB_MAX_COMMIT_COMMENTS = max(1, int(settings.github_max_commit_comments))
GITHUB_MAX_TIMELINE_EVENTS = max(1, int(settings.github_max_timeline_events))
GITHUB_MAX_USER_EVENTS = max(1, int(settings.github_max_user_events))
GITHUB_MAX_COMMIT_DIFF_FETCH = max(1, int(settings.github_max_commit_diff_fetch))
RECENT_WINDOW_DAYS = 90
MID_WINDOW_DAYS = 365
MID_WINDOW_KEEP_RATIO = 0.5
HISTORICAL_WINDOW_KEEP_RATIO = 0.25


@dataclass
class GitHubData:
    """Container for all fetched GitHub data for a user."""

    profile: dict[str, Any] = field(default_factory=dict)
    repos: list[dict[str, Any]] = field(default_factory=list)
    commits: list[dict[str, Any]] = field(default_factory=list)
    pull_requests: list[dict[str, Any]] = field(default_factory=list)
    review_comments: list[dict[str, Any]] = field(default_factory=list)
    issue_comments: list[dict[str, Any]] = field(default_factory=list)
    pull_request_reviews: list[dict[str, Any]] = field(default_factory=list)
    repo_languages: dict[str, dict[str, int]] = field(default_factory=dict)
    commit_diffs: list[dict[str, Any]] = field(default_factory=list)
    pr_review_threads: list[dict[str, Any]] = field(default_factory=list)
    issue_threads: list[dict[str, Any]] = field(default_factory=list)
    pr_commits: list[dict[str, Any]] = field(default_factory=list)
    reviews_authored: list[dict[str, Any]] = field(default_factory=list)
    inline_review_comments: list[dict[str, Any]] = field(default_factory=list)
    starred_repos: list[dict[str, Any]] = field(default_factory=list)
    watched_repos: list[dict[str, Any]] = field(default_factory=list)
    gists: list[dict[str, Any]] = field(default_factory=list)
    commit_comments: list[dict[str, Any]] = field(default_factory=list)
    timeline_events: list[dict[str, Any]] = field(default_factory=list)
    stop_reasons: list[dict[str, Any]] = field(default_factory=list)


def classify_recency_window(
    evidence_date: datetime | None,
    *,
    now: datetime | None = None,
) -> str:
    """Classify evidence into recent/mid/historical windows.

    - recent: 0-90 days old
    - mid: 91-365 days old
    - historical: >365 days old
    """
    if evidence_date is None:
        return "recent"

    now_utc = now or datetime.now(timezone.utc)
    dt = evidence_date.astimezone(timezone.utc)
    age_days = max(0, (now_utc - dt).days)
    if age_days <= RECENT_WINDOW_DAYS:
        return "recent"
    if age_days <= MID_WINDOW_DAYS:
        return "mid"
    return "historical"


def sampling_keep_ratio(window: str) -> float:
    if window == "recent":
        return 1.0
    if window == "mid":
        return MID_WINDOW_KEEP_RATIO
    return HISTORICAL_WINDOW_KEEP_RATIO


def _headers() -> dict[str, str]:
    # mercy-preview enables topics; squirrel-girl includes reactions on comments/issues.
    headers = {
        "Accept": (
            "application/vnd.github+json, "
            "application/vnd.github.mercy-preview+json, "
            "application/vnd.github.squirrel-girl-preview+json"
        )
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


def _record_stop_reason(
    stop_reasons: list[dict[str, Any]],
    *,
    phase: str,
    stop_reason: str,
    **extra: Any,
) -> None:
    stop_reasons.append({"source": "github", "phase": phase, "stop_reason": stop_reason, **extra})


def _repo_owner(repo_full_name: str) -> str:
    if "/" not in repo_full_name:
        return ""
    return repo_full_name.split("/", 1)[0].strip().lower()


def _repo_allowed_by_org_policy(repo_full_name: str, username: str) -> bool:
    if not repo_full_name:
        return True
    if settings.github_include_org_data:
        return True
    owner = _repo_owner(repo_full_name)
    if not owner:
        return True
    if owner == username.casefold():
        return True
    return owner in settings.github_org_allowlist_set


def _parse_event_target(event: dict[str, Any]) -> tuple[str, int] | None:
    repo = (event.get("repo") or {}).get("name") or ""
    payload = event.get("payload") or {}
    for key in ("pull_request", "issue"):
        node = payload.get(key) or {}
        number = node.get("number")
        if repo and number:
            try:
                return repo, int(number)
            except (TypeError, ValueError):
                return None
    return None


async def _get(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    *,
    phase: str | None = None,
    stop_reasons: list[dict[str, Any]] | None = None,
) -> Any:
    """Make a GET request, handling rate limits and errors."""
    resp = await gh_request(client, "GET", url, params=params)
    if resp.status_code == 429 or (
        resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0"
    ):
        logger.warning("GitHub rate limit hit for %s", url)
        if phase and stop_reasons is not None:
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="rate_budget_exhausted",
                url=url,
            )
        return None
    if resp.status_code == 422:
        # GitHub search validation error — skip
        logger.warning("GitHub 422 for %s: %s", url, resp.text[:200])
        if phase and stop_reasons is not None:
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="error",
                url=url,
                status_code=422,
            )
        return None
    resp.raise_for_status()
    return resp.json()


async def _get_paginated(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    max_pages: int | None = None,
    item_cap: int | None = None,
    *,
    phase: str,
    stop_reasons: list[dict[str, Any]],
) -> list[dict]:
    """Fetch paginated results, following Link headers up to max_pages."""
    all_items: list[dict] = []
    params = dict(params or {})
    params.setdefault("per_page", "100")
    pages_fetched = 0

    while True:
        resp = await gh_request(client, "GET", url, params=params)
        if resp.status_code == 429 or (
            resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0"
        ):
            logger.warning("GitHub rate limit hit for %s", url)
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="rate_budget_exhausted",
                url=url,
                pages_fetched=pages_fetched,
                items_emitted=len(all_items),
            )
            break
        if resp.status_code == 422:
            logger.warning("GitHub 422 for %s: %s", url, resp.text[:200])
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="error",
                url=url,
                status_code=422,
                pages_fetched=pages_fetched,
                items_emitted=len(all_items),
            )
            break
        resp.raise_for_status()

        items = resp.json()
        if not isinstance(items, list):
            break
        if not items:
            break

        if item_cap is not None:
            remaining = item_cap - len(all_items)
            if remaining <= 0:
                _record_stop_reason(
                    stop_reasons,
                    phase=phase,
                    stop_reason="item_cap_reached",
                    pages_fetched=pages_fetched,
                    items_emitted=len(all_items),
                )
                break
            all_items.extend(items[:remaining])
        else:
            all_items.extend(items)

        pages_fetched += 1
        if item_cap is not None and len(all_items) >= item_cap:
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="item_cap_reached",
                pages_fetched=pages_fetched,
                items_emitted=len(all_items),
            )
            break
        if max_pages is not None and pages_fetched >= max_pages:
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="item_cap_reached",
                pages_fetched=pages_fetched,
                items_emitted=len(all_items),
            )
            break

        # Check for next page via Link header
        link_header = resp.headers.get("Link", "")
        if 'rel="next"' not in link_header:
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="cursor_complete",
                pages_fetched=pages_fetched,
                items_emitted=len(all_items),
            )
            break
        # Extract next URL
        next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        if not next_match:
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="cursor_complete",
                pages_fetched=pages_fetched,
                items_emitted=len(all_items),
            )
            break
        url = next_match.group(1)
        params = {}  # URL already contains params

    return all_items


async def _get_search_items_paginated(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str],
    *,
    item_cap: int,
    phase: str,
    stop_reasons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fetch search API ``items`` pages until exhausted or cap reached."""
    all_items: list[dict[str, Any]] = []
    page = 1
    per_page = min(100, max(1, item_cap))

    while len(all_items) < item_cap:
        response = await _get(
            client,
            url,
            params={**params, "per_page": str(per_page), "page": str(page)},
            phase=phase,
            stop_reasons=stop_reasons,
        )
        if not isinstance(response, dict):
            break
        items = response.get("items")
        if not isinstance(items, list) or not items:
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="cursor_complete",
                page=page,
                items_emitted=len(all_items),
            )
            break

        remaining = item_cap - len(all_items)
        all_items.extend(items[:remaining])
        if len(all_items) >= item_cap:
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="item_cap_reached",
                page=page,
                items_emitted=len(all_items),
            )
            break

        if len(items) < per_page:
            _record_stop_reason(
                stop_reasons,
                phase=phase,
                stop_reason="cursor_complete",
                page=page,
                items_emitted=len(all_items),
            )
            break
        page += 1

    return all_items


def _repo_full_name_from_pr(pr: dict[str, Any]) -> str:
    """Extract ``owner/repo`` from a GitHub issue-search PR item."""
    base_repo = (pr.get("base") or {}).get("repo") or {}
    if base_repo.get("full_name"):
        return base_repo["full_name"]

    repo = pr.get("repo")
    if isinstance(repo, str) and repo:
        return repo
    if isinstance(repo, dict) and repo.get("full_name"):
        return repo["full_name"]

    repo_url = pr.get("repository_url") or ""
    if "/repos/" in repo_url:
        return repo_url.rsplit("/repos/", 1)[1]
    return ""


def _repo_from_commit(commit: dict[str, Any]) -> str:
    return (commit.get("repository") or {}).get("full_name") or ""


def _repo_from_review_event(review: dict[str, Any]) -> str:
    return review.get("repo") or ""


def _repo_from_thread(thread: dict[str, Any]) -> str:
    return thread.get("repo") or ""


def build_repo_activity_summary(data: GitHubData) -> dict[str, dict[str, Any]]:
    """Build per-repo activity stats for ingestion-side diversity rules."""
    summary: dict[str, dict[str, Any]] = {}

    def ensure(repo_name: str) -> dict[str, Any]:
        return summary.setdefault(
            repo_name,
            {
                "repo": repo_name,
                "estimated_loc": 0,
                "commit_count": 0,
                "pr_count": 0,
                "non_trivial": False,
            },
        )

    for repo in data.repos:
        repo_name = repo.get("full_name") or repo.get("name") or ""
        if not repo_name:
            continue
        entry = ensure(repo_name)
        # GitHub REST repo.size is KB. Conservative LOC estimate for breadth gating.
        size_kb = int(repo.get("size") or 0)
        size_loc_estimate = size_kb * 30
        lang_total_bytes = sum((data.repo_languages.get(repo_name) or {}).values())
        lang_loc_estimate = int(lang_total_bytes / 40) if lang_total_bytes else 0
        entry["estimated_loc"] = max(size_loc_estimate, lang_loc_estimate)

    for commit in data.commits:
        repo_name = _repo_from_commit(commit)
        if not repo_name:
            continue
        ensure(repo_name)["commit_count"] += 1

    prs_by_repo: dict[str, set[int]] = {}
    for pr in data.pull_requests:
        repo_name = _repo_full_name_from_pr(pr)
        number = pr.get("number")
        if not repo_name or not number:
            continue
        ensure(repo_name)
        prs_by_repo.setdefault(repo_name, set()).add(int(number))

    for thread in data.pr_review_threads:
        repo_name = _repo_from_thread(thread)
        number = thread.get("pr_number")
        if not repo_name or not number:
            continue
        ensure(repo_name)
        prs_by_repo.setdefault(repo_name, set()).add(int(number))

    for thread in data.issue_threads:
        repo_name = _repo_from_thread(thread)
        number = thread.get("pr_number")
        if not repo_name or not number:
            continue
        ensure(repo_name)
        prs_by_repo.setdefault(repo_name, set()).add(int(number))

    for review in data.pull_request_reviews:
        repo_name = _repo_from_review_event(review)
        number = review.get("pr_number")
        if not repo_name or not number:
            continue
        ensure(repo_name)
        prs_by_repo.setdefault(repo_name, set()).add(int(number))

    for repo_name, pr_numbers in prs_by_repo.items():
        ensure(repo_name)["pr_count"] = len(pr_numbers)

    for repo_name, stats in summary.items():
        stats["non_trivial"] = is_non_trivial_repo(stats)
        summary[repo_name] = stats

    return summary


def is_non_trivial_repo(repo_stats: dict[str, Any]) -> bool:
    return bool(
        int(repo_stats.get("estimated_loc") or 0) > 100
        or int(repo_stats.get("commit_count") or 0) > 10
        or int(repo_stats.get("pr_count") or 0) > 1
    )


def _author_login(item: dict[str, Any]) -> str:
    user = item.get("user") or item.get("author") or {}
    if isinstance(user, dict):
        return user.get("login") or ""
    return ""


def _append_unique_by_id(items: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
    """Append GitHub objects without duplicating already-seen IDs."""
    seen = {str(item.get("id")) for item in items if item.get("id") is not None}
    for candidate in candidates:
        item_id = candidate.get("id")
        if item_id is None:
            continue
        item_id_str = str(item_id)
        if item_id_str in seen:
            continue
        items.append(candidate)
        seen.add(item_id_str)


def _flatten_thread_comments(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten thread snapshots into comment objects."""
    comments: list[dict[str, Any]] = []
    for thread in threads:
        thread_comments = thread.get("comments") or []
        if not isinstance(thread_comments, list):
            continue
        comments.extend(comment for comment in thread_comments if isinstance(comment, dict))
    return comments


def _pr_identity(pr: dict[str, Any]) -> tuple[str, int] | None:
    repo = _repo_full_name_from_pr(pr)
    number = pr.get("number")
    if not repo or not number:
        return None
    try:
        return repo, int(number)
    except (TypeError, ValueError):
        return None


async def fetch_commit_diffs(
    client: httpx.AsyncClient,
    commits: list[dict[str, Any]],
    *,
    max_commits: int = GITHUB_MAX_COMMIT_DIFF_FETCH,
    stop_reasons: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch detailed commit files/patches for recent authored commits."""
    diffs: list[dict[str, Any]] = []

    for commit in commits[:max_commits]:
        sha = commit.get("sha") or commit.get("commit", {}).get("sha")
        repo_name = (commit.get("repository") or {}).get("full_name")
        if not sha or not repo_name:
            continue

        detail = await _get(
            client,
            f"/repos/{repo_name}/commits/{sha}",
            phase="commit_diffs",
            stop_reasons=stop_reasons or [],
        )
        if not isinstance(detail, dict):
            continue

        detail["repo"] = repo_name
        detail["sha"] = detail.get("sha") or sha
        diffs.append(detail)

    return diffs


def _group_pr_review_threads(
    repo: str,
    pr_number: int,
    pr_node_id: str,
    comments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group REST PR review comments into reply chains using ``in_reply_to_id``."""
    by_thread: dict[str, list[dict[str, Any]]] = {}
    for comment in comments:
        root_id = comment.get("in_reply_to_id") or comment.get("id")
        if root_id is None:
            continue
        by_thread.setdefault(str(root_id), []).append(comment)

    threads: list[dict[str, Any]] = []
    for root_id, thread_comments in by_thread.items():
        thread_comments.sort(key=lambda c: c.get("created_at") or "")
        first = thread_comments[0]
        threads.append(
            {
                "thread_id": f"{repo}#{pr_number}:{root_id}",
                "repo": repo,
                "pr_number": pr_number,
                "pr_node_id": pr_node_id,
                "path": first.get("path") or "",
                "line": first.get("line"),
                "original_line": first.get("original_line"),
                "start_line": first.get("start_line"),
                "side": first.get("side"),
                "diff_hunk": first.get("diff_hunk") or "",
                "comments": thread_comments,
            }
        )

    return threads


async def fetch_pr_discussions(
    client: httpx.AsyncClient,
    pull_requests: list[dict[str, Any]],
    username: str,
    *,
    max_prs: int = GITHUB_MAX_PRS,
    stop_reasons: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch paginated PR issue discussions and review comment threads.

    Returns ``(issue_threads, review_threads, issue_comments,
    review_comments)``. Thread snapshots preserve public comments on selected
    PRs so extraction can use target, audience, and timing.
    """
    issue_threads: list[dict[str, Any]] = []
    review_threads: list[dict[str, Any]] = []
    issue_comments_all: list[dict[str, Any]] = []
    review_comments_all: list[dict[str, Any]] = []
    stops = stop_reasons or []
    subject_login = username.casefold()

    for pr in pull_requests[:max_prs]:
        number = pr.get("number")
        repo = _repo_full_name_from_pr(pr)
        if not number or not repo:
            continue

        pr_node_id = pr.get("node_id") or f"{repo}#{number}"

        issue_comments = await _get_paginated(
            client,
            f"/repos/{repo}/issues/{number}/comments",
            item_cap=GITHUB_MAX_ISSUE_COMMENTS_PER_PR,
            phase="pr_issue_comments",
            stop_reasons=stops,
        )
        if issue_comments:
            issue_threads.append(
                {
                    "repo": repo,
                    "pr_number": number,
                    "pr_node_id": pr_node_id,
                    "html_url": pr.get("html_url") or "",
                    "comments": issue_comments,
                }
            )
            issue_comments_all.extend(
                [
                    comment
                    for comment in issue_comments
                    if _author_login(comment).casefold() == subject_login
                ]
            )

        review_comments = await _get_paginated(
            client,
            f"/repos/{repo}/pulls/{number}/comments",
            item_cap=GITHUB_MAX_REVIEW_COMMENTS_PER_PR,
            phase="pr_review_comments",
            stop_reasons=stops,
        )
        if review_comments:
            review_threads.extend(
                _group_pr_review_threads(repo, int(number), str(pr_node_id), review_comments)
            )
            review_comments_all.extend(
                [
                    comment
                    for comment in review_comments
                    if _author_login(comment).casefold() == subject_login
                ]
            )

    return issue_threads, review_threads, issue_comments_all, review_comments_all


async def fetch_pr_reviews(
    client: httpx.AsyncClient,
    pull_requests: list[dict[str, Any]],
    *,
    max_prs: int = GITHUB_MAX_PRS,
    stop_reasons: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch PR review state events for selected pull requests.

    Review events capture temporal approval/request-changes/comment state even
    when the body is empty. That timeline is critical for learning whether a
    reviewer blocks, approves, reverses, or ratifies after follow-up changes.
    """
    reviews: list[dict[str, Any]] = []
    stops = stop_reasons or []

    for pr in pull_requests[:max_prs]:
        identity = _pr_identity(pr)
        if identity is None:
            continue
        repo, number = identity
        pr_node_id = pr.get("node_id") or f"{repo}#{number}"
        pr_url = pr.get("html_url") or f"https://github.com/{repo}/pull/{number}"

        pr_reviews = await _get_paginated(
            client,
            f"/repos/{repo}/pulls/{number}/reviews",
            phase="pr_reviews",
            stop_reasons=stops,
        )
        for review in pr_reviews:
            if not isinstance(review, dict):
                continue
            review["repo"] = review.get("repo") or repo
            review["pr_number"] = review.get("pr_number") or number
            review["pr_node_id"] = review.get("pr_node_id") or pr_node_id
            review["pr_html_url"] = review.get("pr_html_url") or pr_url
            reviews.append(review)

    return reviews


async def fetch_pr_commit_lists(
    client: httpx.AsyncClient,
    pull_requests: list[dict[str, Any]],
    *,
    max_prs: int = GITHUB_MAX_PRS,
    stop_reasons: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch commit SHA lists for selected PRs."""
    pr_commits: list[dict[str, Any]] = []
    stops = stop_reasons or []

    for pr in pull_requests[:max_prs]:
        identity = _pr_identity(pr)
        if identity is None:
            continue
        repo, number = identity
        commits = await _get_paginated(
            client,
            f"/repos/{repo}/pulls/{number}/commits",
            phase="pr_commit_lists",
            stop_reasons=stops,
        )
        if not commits:
            continue

        commit_shas = [str(c.get("sha")) for c in commits if c.get("sha")]
        if not commit_shas:
            continue

        pr_commits.append(
            {
                "repo": repo,
                "pr_number": number,
                "pr_node_id": pr.get("node_id") or f"{repo}#{number}",
                "html_url": pr.get("html_url") or f"https://github.com/{repo}/pull/{number}",
                "commit_shas": commit_shas,
            }
        )

    return pr_commits


def _coerce_commit_comment(comment: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    repo = (event.get("repo") or {}).get("name") or ""
    payload = event.get("payload") or {}
    commit_id = comment.get("commit_id") or payload.get("comment", {}).get("commit_id") or ""
    comment["repo"] = comment.get("repo") or repo
    if commit_id:
        comment["commit_id"] = commit_id
    if event.get("created_at") and not comment.get("created_at"):
        comment["created_at"] = event["created_at"]
    return comment


def extract_timeline_events_from_user_events(
    events: list[dict[str, Any]],
    *,
    selected_targets: set[tuple[str, int]],
    max_events: int,
) -> list[dict[str, Any]]:
    """Extract issue/PR timeline events from user activity events in bulk."""
    timeline_events: list[dict[str, Any]] = []
    supported_types = {
        "PullRequestEvent",
        "PullRequestReviewEvent",
        "PullRequestReviewCommentEvent",
        "IssueCommentEvent",
        "IssuesEvent",
    }
    for event in events:
        event_type = event.get("type") or ""
        if event_type not in supported_types:
            continue
        target = _parse_event_target(event)
        if target is None or target not in selected_targets:
            continue
        payload = event.get("payload") or {}
        timeline_events.append(
            {
                "id": event.get("id"),
                "type": event_type,
                "repo": target[0],
                "number": target[1],
                "action": payload.get("action"),
                "created_at": event.get("created_at"),
                "actor": (event.get("actor") or {}).get("login"),
                "payload": payload,
            }
        )
        if len(timeline_events) >= max_events:
            break
    return timeline_events


_GRAPHQL_REPOS_QUERY = """
query($login: String!) {
  user(login: $login) {
    repositories(first: 100, ownerAffiliations: OWNER,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes {
        name
        nameWithOwner
        description
        stargazerCount
        pushedAt
        isFork
        isArchived
        repositoryTopics(first: 20) {
          nodes { topic { name } }
        }
        primaryLanguage { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
""".strip()


_GRAPHQL_REVIEWS_AUTHORED_QUERY = """
query($login: String!, $first: Int!, $after: String) {
  user(login: $login) {
    contributionsCollection {
      pullRequestReviewContributions(first: $first, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          pullRequest {
            number
            repository {
              owner { login }
              name
            }
          }
          pullRequestReview {
            id
            body
            state
            submittedAt
            comments(first: 100) {
              nodes {
                id
                body
                path
                diffHunk
                line
                startLine
              }
            }
          }
        }
      }
    }
  }
}
""".strip()


async def fetch_user_repos_graphql(
    client: httpx.AsyncClient, username: str, top_n: int = 100
) -> tuple[list[dict], dict[str, dict[str, int]]] | None:
    """Fetch top repos and per-repo language breakdowns via GraphQL in one round-trip.

    Collapses the REST ``GET /users/:login/repos`` + N x
    ``GET /repos/:full_name/languages`` pattern into a single GraphQL query.

    Returns a tuple ``(repos, repo_languages)`` where:

    - ``repos`` is a list of dicts shaped like REST ``/users/:login/repos``
      items (fields: ``name``, ``full_name``, ``description``, ``language``,
      ``stargazers_count``, ``topics``, ``pushed_at``, ``fork``, ``archived``).
    - ``repo_languages`` maps ``full_name -> {lang_name: size_in_bytes}``.

    Returns ``None`` on any failure (non-200, ``errors`` array, exception) so
    callers can fall back to the REST path.
    """
    headers = _headers()
    # GraphQL endpoint expects application/json, not the mercy-preview accept.
    headers = {**headers, "Accept": "application/json"}

    try:
        resp = await gh_request(
            client,
            "POST",
            "/graphql",
            headers=headers,
            json={
                "query": _GRAPHQL_REPOS_QUERY,
                "variables": {"login": username},
            },
        )
    except Exception as exc:
        logger.warning("GraphQL request failed for %s: %r", username, exc)
        return None

    if resp.status_code != 200:
        logger.warning(
            "GraphQL non-200 for %s: %s %s",
            username,
            resp.status_code,
            resp.text[:200],
        )
        return None

    try:
        body = resp.json()
    except Exception:
        logger.warning("GraphQL returned non-JSON for %s", username)
        return None

    if body.get("errors"):
        logger.warning("GraphQL errors for %s: %s", username, body["errors"])
        return None

    user_data = (body.get("data") or {}).get("user")
    if not user_data:
        return None

    nodes = (user_data.get("repositories") or {}).get("nodes") or []

    repos: list[dict] = []
    repo_languages: dict[str, dict[str, int]] = {}

    for node in nodes[:top_n]:
        if not isinstance(node, dict):
            continue

        full_name = node.get("nameWithOwner") or ""
        topic_wrapper = node.get("repositoryTopics") or {}
        topic_nodes = topic_wrapper.get("nodes") or []
        topics = [
            t.get("topic", {}).get("name") for t in topic_nodes if t.get("topic", {}).get("name")
        ]
        primary = (node.get("primaryLanguage") or {}).get("name")

        repos.append(
            {
                "name": node.get("name"),
                "full_name": full_name,
                "description": node.get("description"),
                "language": primary,
                "stargazers_count": node.get("stargazerCount", 0) or 0,
                "topics": topics,
                "pushed_at": node.get("pushedAt"),
                "fork": node.get("isFork", False),
                "archived": node.get("isArchived", False),
            }
        )

        lang_edges = (node.get("languages") or {}).get("edges") or []
        lang_map: dict[str, int] = {}
        for edge in lang_edges:
            lang_name = (edge.get("node") or {}).get("name")
            size = edge.get("size", 0) or 0
            if lang_name:
                lang_map[lang_name] = size
        if full_name and lang_map:
            repo_languages[full_name] = lang_map

    return repos, repo_languages


async def fetch_reviews_authored_graphql(
    client: httpx.AsyncClient,
    username: str,
    *,
    max_reviews: int = GITHUB_MAX_REVIEWS_AUTHORED,
) -> list[dict[str, Any]]:
    """Fetch PR reviews authored by the user via GraphQL contributions."""
    headers = {**_headers(), "Accept": "application/json"}
    reviews: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(reviews) < max_reviews:
        page_size = min(100, max_reviews - len(reviews))
        response = await gh_request(
            client,
            "POST",
            "/graphql",
            headers=headers,
            json={
                "query": _GRAPHQL_REVIEWS_AUTHORED_QUERY,
                "variables": {
                    "login": username,
                    "first": page_size,
                    "after": cursor,
                },
            },
        )
        if response.status_code != 200:
            logger.warning(
                "GraphQL review contributions non-200 for %s: %s %s",
                username,
                response.status_code,
                response.text[:200],
            )
            break

        try:
            payload = response.json()
        except ValueError:
            logger.warning("GraphQL review contributions non-JSON for %s", username)
            break
        if payload.get("errors"):
            logger.warning(
                "GraphQL review contributions errors for %s: %s",
                username,
                payload["errors"],
            )
            break

        contrib = (
            (payload.get("data") or {})
            .get("user", {})
            .get("contributionsCollection", {})
            .get("pullRequestReviewContributions", {})
        )
        nodes = contrib.get("nodes") or []
        if not nodes:
            break

        for node in nodes:
            pull_request = node.get("pullRequest") or {}
            repository = pull_request.get("repository") or {}
            owner = (repository.get("owner") or {}).get("login") or ""
            repo = repository.get("name") or ""
            pr_number = pull_request.get("number")
            review = node.get("pullRequestReview") or {}
            review_id = review.get("id")
            if not owner or not repo or not pr_number or not review_id:
                continue
            reviews.append(
                {
                    "owner": owner,
                    "repo": repo,
                    "pr_number": int(pr_number),
                    "review_id": str(review_id),
                    "body": review.get("body") or "",
                    "state": review.get("state") or "",
                    "submitted_at": review.get("submittedAt"),
                    "comments": (review.get("comments") or {}).get("nodes") or [],
                }
            )
            if len(reviews) >= max_reviews:
                break

        page_info = contrib.get("pageInfo") or {}
        if len(reviews) >= max_reviews or not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break

    return reviews


async def fetch_inline_review_comments_for_prs(
    client: httpx.AsyncClient,
    pull_requests: list[dict[str, Any]],
    *,
    max_comments: int = GITHUB_MAX_INLINE_COMMENTS,
    stop_reasons: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch inline review comments for provided PRs (REST endpoint)."""
    inline_comments: list[dict[str, Any]] = []
    stops = stop_reasons or []

    for pr in pull_requests:
        if len(inline_comments) >= max_comments:
            break
        identity = _pr_identity(pr)
        if identity is None:
            continue
        repo, number = identity
        remaining = max_comments - len(inline_comments)
        comments = await _get_paginated(
            client,
            f"/repos/{repo}/pulls/{number}/comments",
            item_cap=remaining,
            phase="inline_review_comments",
            stop_reasons=stops,
        )
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            comment["repo"] = comment.get("repo") or repo
            comment["pr_number"] = comment.get("pr_number") or number
            inline_comments.append(comment)
            if len(inline_comments) >= max_comments:
                break

    return inline_comments


async def fetch_starred_repos(
    client: httpx.AsyncClient,
    username: str,
    *,
    max_starred: int = GITHUB_MAX_STARRED,
    stop_reasons: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch starred repositories for the user."""
    return await _get_paginated(
        client,
        f"/users/{username}/starred",
        params={"per_page": "100"},
        item_cap=max_starred,
        phase="starred_repos",
        stop_reasons=stop_reasons or [],
    )


async def fetch_watched_repos(
    client: httpx.AsyncClient,
    username: str,
    *,
    max_watched: int = GITHUB_MAX_WATCHED,
    stop_reasons: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch watched/subscribed repositories for the user."""
    return await _get_paginated(
        client,
        f"/users/{username}/subscriptions",
        params={"per_page": "100"},
        item_cap=max_watched,
        phase="watched_repos",
        stop_reasons=stop_reasons or [],
    )


async def _fetch_gist_file_content(client: httpx.AsyncClient, raw_url: str) -> str:
    """Fetch raw gist file content via URL."""
    if not raw_url:
        return ""
    response = await gh_request(client, "GET", raw_url)
    if response.status_code >= 400:
        return ""
    return response.text


async def fetch_gists_with_files(
    client: httpx.AsyncClient,
    username: str,
    *,
    max_gists: int = GITHUB_MAX_GISTS,
    stop_reasons: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch gists and include file contents via content or raw_url."""
    gists = await _get_paginated(
        client,
        f"/users/{username}/gists",
        params={"per_page": "100"},
        item_cap=max_gists,
        phase="gists",
        stop_reasons=stop_reasons or [],
    )

    enriched_gists: list[dict[str, Any]] = []
    for gist in gists:
        if not isinstance(gist, dict):
            continue
        files = gist.get("files")
        if not isinstance(files, dict):
            continue
        enriched_files: list[dict[str, Any]] = []
        for file_info in files.values():
            if not isinstance(file_info, dict):
                continue
            file_content = file_info.get("content")
            if not file_content and file_info.get("raw_url"):
                file_content = await _fetch_gist_file_content(client, str(file_info["raw_url"]))
            enriched_files.append(
                {
                    "filename": file_info.get("filename") or "",
                    "language": file_info.get("language"),
                    "type": file_info.get("type"),
                    "size": file_info.get("size"),
                    "raw_url": file_info.get("raw_url"),
                    "content": file_content or "",
                }
            )
        gist["files_enriched"] = enriched_files
        enriched_gists.append(gist)
    return enriched_gists


async def fetch_github_data(username: str) -> GitHubData:
    """Fetch all available GitHub activity for a user."""
    data = GitHubData()
    stop_reasons = data.stop_reasons

    async with httpx.AsyncClient(base_url=API_BASE, headers=_headers(), timeout=30.0) as client:
        # 1. User profile
        profile = await _get(
            client,
            f"/users/{username}",
            phase="profile",
            stop_reasons=stop_reasons,
        )
        if profile:
            data.profile = profile

        # 2. Repos + languages — try GraphQL first (single round-trip for both),
        # fall back to the REST loop (paginated repos + N per-repo language
        # requests) on any failure.
        graphql_result = await fetch_user_repos_graphql(
            client, username, top_n=min(100, GITHUB_MAX_REPOS)
        )
        if graphql_result is not None:
            repos, repo_langs = graphql_result
            if repos:
                data.repos = repos
                data.repo_languages = repo_langs
                logger.info(
                    "Fetched %d repos via GraphQL for %s (%d with languages)",
                    len(repos),
                    username,
                    len(repo_langs),
                )
        else:
            _record_stop_reason(
                stop_reasons,
                phase="repos_graphql",
                stop_reason="fallback_used",
                fallback={"from": "graphql", "to": "rest", "reason": "graphql_empty_or_error"},
            )

        if not data.repos:
            repos = await _get_paginated(
                client,
                f"/users/{username}/repos",
                params={"sort": "pushed", "per_page": "100", "type": "owner"},
                item_cap=GITHUB_MAX_REPOS,
                phase="repos_rest",
                stop_reasons=stop_reasons,
            )
            if repos:
                data.repos = repos

                # Per-repo language breakdown for top repos (env-tunable).
                for repo in repos[:GITHUB_MAX_REPOS_WITH_LANGUAGES]:
                    repo_name = repo.get("full_name") or repo.get("name", "")
                    if not repo_name:
                        continue
                    langs = await _get(
                        client,
                        f"/repos/{repo_name}/languages",
                        phase="repo_languages",
                        stop_reasons=stop_reasons,
                    )
                    if langs and isinstance(langs, dict):
                        data.repo_languages[repo_name] = langs

        # 3. Recent commits (search API)
        commits = await _get_search_items_paginated(
            client,
            "/search/commits",
            params={
                "q": f"author:{username}",
                "sort": "author-date",
            },
            item_cap=GITHUB_MAX_COMMITS,
            phase="commits_search",
            stop_reasons=stop_reasons,
        )
        if commits:
            data.commits = commits
            data.commit_diffs = await fetch_commit_diffs(
                client,
                data.commits,
                max_commits=GITHUB_MAX_COMMIT_DIFF_FETCH,
                stop_reasons=stop_reasons,
            )

        # 4. PRs authored
        authored_prs = await _get_search_items_paginated(
            client,
            "/search/issues",
            params={
                "q": f"author:{username} type:pr",
                "sort": "updated",
            },
            item_cap=GITHUB_MAX_PRS,
            phase="prs_authored_search",
            stop_reasons=stop_reasons,
        )
        if authored_prs:
            data.pull_requests = authored_prs
            (
                data.issue_threads,
                data.pr_review_threads,
                issue_comments,
                review_comments,
            ) = await fetch_pr_discussions(
                client,
                data.pull_requests,
                username,
                stop_reasons=stop_reasons,
            )
            data.pull_request_reviews = await fetch_pr_reviews(
                client,
                data.pull_requests,
                stop_reasons=stop_reasons,
            )
            data.pr_commits = await fetch_pr_commit_lists(
                client,
                data.pull_requests,
                stop_reasons=stop_reasons,
            )
            data.inline_review_comments = await fetch_inline_review_comments_for_prs(
                client,
                data.pull_requests,
                stop_reasons=stop_reasons,
            )
            _append_unique_by_id(data.issue_comments, issue_comments)
            _append_unique_by_id(data.review_comments, review_comments)
            # Preserve complete thread snapshots for evidence surfaces that
            # need non-subject comments as context.
            _append_unique_by_id(data.issue_comments, _flatten_thread_comments(data.issue_threads))
            _append_unique_by_id(data.review_comments, _flatten_thread_comments(data.pr_review_threads))

        # 5. Review comments — fetch from recent PR-related events
        # Use the events API to find IssueCommentEvent and PullRequestReviewCommentEvent
        events = await _get_paginated(
            client,
            f"/users/{username}/events",
            params={"per_page": "100"},
            item_cap=GITHUB_MAX_USER_EVENTS,
            phase="user_events",
            stop_reasons=stop_reasons,
        )
        if events:
            selected_targets: set[tuple[str, int]] = set()
            for pr in data.pull_requests:
                identity = _pr_identity(pr)
                if identity is not None:
                    selected_targets.add(identity)
            for event in events:
                etype = event.get("type", "")
                payload = event.get("payload", {})
                if etype == "PullRequestReviewCommentEvent":
                    comment = payload.get("comment", {})
                    if comment:
                        _append_unique_by_id(data.review_comments, [comment])
                elif etype == "IssueCommentEvent":
                    comment = payload.get("comment", {})
                    if comment:
                        _append_unique_by_id(data.issue_comments, [comment])
                elif etype == "CommitCommentEvent":
                    comment = payload.get("comment", {})
                    if isinstance(comment, dict):
                        data.commit_comments.append(_coerce_commit_comment(comment, event))
            data.timeline_events = extract_timeline_events_from_user_events(
                events,
                selected_targets=selected_targets,
                max_events=GITHUB_MAX_TIMELINE_EVENTS,
            )

        # 6. PRs where the subject commented/reviewed are often the highest
        # signal for decision frameworks. Search complements the shallow events
        # window and lets us preserve review states, not only inline comments.
        reviewed_pr_items = await _get_search_items_paginated(
            client,
            "/search/issues",
            params={
                "q": f"commenter:{username} type:pr",
                "sort": "updated",
            },
            item_cap=GITHUB_MAX_ISSUES,
            phase="prs_reviewed_search",
            stop_reasons=stop_reasons,
        )
        if reviewed_pr_items:
            authored_prs = {
                identity for pr in data.pull_requests if (identity := _pr_identity(pr)) is not None
            }
            reviewed_prs = [
                pr
                for pr in reviewed_pr_items
                if (identity := _pr_identity(pr)) is not None
                and identity not in authored_prs
            ]
            (
                reviewed_issue_threads,
                reviewed_review_threads,
                reviewed_issue_comments,
                reviewed_review_comments,
            ) = await fetch_pr_discussions(
                client,
                reviewed_prs,
                username,
                max_prs=GITHUB_MAX_PRS,
                stop_reasons=stop_reasons,
            )
            data.issue_threads.extend(reviewed_issue_threads)
            data.pr_review_threads.extend(reviewed_review_threads)
            _append_unique_by_id(data.issue_comments, reviewed_issue_comments)
            _append_unique_by_id(data.review_comments, reviewed_review_comments)
            _append_unique_by_id(data.issue_comments, _flatten_thread_comments(reviewed_issue_threads))
            _append_unique_by_id(data.review_comments, _flatten_thread_comments(reviewed_review_threads))
            data.pr_commits.extend(
                await fetch_pr_commit_lists(
                    client,
                    reviewed_prs,
                    max_prs=GITHUB_MAX_PRS,
                    stop_reasons=stop_reasons,
                )
            )
            _append_unique_by_id(
                data.pull_request_reviews,
                await fetch_pr_reviews(
                    client,
                    reviewed_prs,
                    max_prs=GITHUB_MAX_PRS,
                    stop_reasons=stop_reasons,
                ),
            )

        data.reviews_authored = await fetch_reviews_authored_graphql(client, username)
        data.starred_repos = await fetch_starred_repos(client, username, stop_reasons=stop_reasons)
        data.watched_repos = await fetch_watched_repos(client, username, stop_reasons=stop_reasons)
        data.gists = await fetch_gists_with_files(client, username, stop_reasons=stop_reasons)

    logger.info(
        "Fetched GitHub data for %s: %d repos, %d commits, %d PRs, %d reviews, "
        "%d issue comments, %d PR reviews, %d repo language breakdowns, %d commit diffs, "
        "%d PR review threads, %d issue threads, %d PR commit lists, %d authored reviews, "
        "%d inline comments, %d starred repos, %d watched repos, %d commit comments, "
        "%d timeline events, %d gists, %d stop reasons",
        username,
        len(data.repos),
        len(data.commits),
        len(data.pull_requests),
        len(data.review_comments),
        len(data.issue_comments),
        len(data.pull_request_reviews),
        len(data.repo_languages),
        len(data.commit_diffs),
        len(data.pr_review_threads),
        len(data.issue_threads),
        len(data.pr_commits),
        len(data.reviews_authored),
        len(data.inline_review_comments),
        len(data.starred_repos),
        len(data.watched_repos),
        len(data.commit_comments),
        len(data.timeline_events),
        len(data.gists),
        len(data.stop_reasons),
    )
    return data
