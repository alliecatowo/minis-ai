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
RECENT_WINDOW_DAYS = 90
MID_WINDOW_DAYS = 365


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


def _headers() -> dict[str, str]:
    # mercy-preview enables topics array on repository objects
    headers = {"Accept": "application/vnd.github.mercy-preview+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> Any:
    """Make a GET request, handling rate limits and errors."""
    resp = await gh_request(client, "GET", url, params=params)
    if resp.status_code == 429 or (
        resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0"
    ):
        logger.warning("GitHub rate limit hit for %s", url)
        return None
    if resp.status_code == 422:
        # GitHub search validation error — skip
        logger.warning("GitHub 422 for %s: %s", url, resp.text[:200])
        return None
    resp.raise_for_status()
    return resp.json()


async def _get_paginated(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    max_pages: int | None = None,
    item_cap: int | None = None,
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
            break
        if resp.status_code == 422:
            logger.warning("GitHub 422 for %s: %s", url, resp.text[:200])
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
                break
            all_items.extend(items[:remaining])
        else:
            all_items.extend(items)

        pages_fetched += 1
        if item_cap is not None and len(all_items) >= item_cap:
            break
        if max_pages is not None and pages_fetched >= max_pages:
            break

        # Check for next page via Link header
        link_header = resp.headers.get("Link", "")
        if 'rel="next"' not in link_header:
            break
        # Extract next URL
        next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        if not next_match:
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
        )
        if not isinstance(response, dict):
            break
        items = response.get("items")
        if not isinstance(items, list) or not items:
            break

        remaining = item_cap - len(all_items)
        all_items.extend(items[:remaining])

        if len(items) < per_page:
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
    max_commits: int = GITHUB_MAX_COMMITS,
) -> list[dict[str, Any]]:
    """Fetch detailed commit files/patches for recent authored commits."""
    diffs: list[dict[str, Any]] = []

    for commit in commits[:max_commits]:
        sha = commit.get("sha") or commit.get("commit", {}).get("sha")
        repo_name = (commit.get("repository") or {}).get("full_name")
        if not sha or not repo_name:
            continue

        detail = await _get(client, f"/repos/{repo_name}/commits/{sha}")
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
    _ = username

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
            issue_comments_all.extend(issue_comments)

        review_comments = await _get_paginated(
            client,
            f"/repos/{repo}/pulls/{number}/comments",
            item_cap=GITHUB_MAX_REVIEW_COMMENTS_PER_PR,
        )
        if review_comments:
            review_threads.extend(
                _group_pr_review_threads(repo, int(number), str(pr_node_id), review_comments)
            )
            review_comments_all.extend(review_comments)

    return issue_threads, review_threads, issue_comments_all, review_comments_all


async def fetch_pr_reviews(
    client: httpx.AsyncClient,
    pull_requests: list[dict[str, Any]],
    *,
    max_prs: int = GITHUB_MAX_PRS,
) -> list[dict[str, Any]]:
    """Fetch PR review state events for selected pull requests.

    Review events capture temporal approval/request-changes/comment state even
    when the body is empty. That timeline is critical for learning whether a
    reviewer blocks, approves, reverses, or ratifies after follow-up changes.
    """
    reviews: list[dict[str, Any]] = []

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
) -> list[dict[str, Any]]:
    """Fetch commit SHA lists for selected PRs."""
    pr_commits: list[dict[str, Any]] = []

    for pr in pull_requests[:max_prs]:
        identity = _pr_identity(pr)
        if identity is None:
            continue
        repo, number = identity
        commits = await _get_paginated(client, f"/repos/{repo}/pulls/{number}/commits")
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
        resp = await client.post(
            "https://api.github.com/graphql",
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


async def fetch_github_data(username: str) -> GitHubData:
    """Fetch all available GitHub activity for a user."""
    data = GitHubData()

    async with httpx.AsyncClient(base_url=API_BASE, headers=_headers(), timeout=30.0) as client:
        # 1. User profile
        profile = await _get(client, f"/users/{username}")
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

        if not data.repos:
            repos = await _get_paginated(
                client,
                f"/users/{username}/repos",
                params={"sort": "pushed", "per_page": "100", "type": "owner"},
                item_cap=GITHUB_MAX_REPOS,
            )
            if repos:
                data.repos = repos

                # Per-repo language breakdown for top repos (env-tunable).
                for repo in repos[:GITHUB_MAX_REPOS_WITH_LANGUAGES]:
                    repo_name = repo.get("full_name") or repo.get("name", "")
                    if not repo_name:
                        continue
                    langs = await _get(client, f"/repos/{repo_name}/languages")
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
        )
        if commits:
            data.commits = commits
            data.commit_diffs = await fetch_commit_diffs(client, data.commits)

        # 4. PRs authored
        authored_prs = await _get_search_items_paginated(
            client,
            "/search/issues",
            params={
                "q": f"author:{username} type:pr",
                "sort": "updated",
            },
            item_cap=GITHUB_MAX_PRS,
        )
        if authored_prs:
            data.pull_requests = authored_prs
            (
                data.issue_threads,
                data.pr_review_threads,
                issue_comments,
                review_comments,
            ) = await fetch_pr_discussions(client, data.pull_requests, username)
            data.pull_request_reviews = await fetch_pr_reviews(client, data.pull_requests)
            data.pr_commits = await fetch_pr_commit_lists(client, data.pull_requests)
            _append_unique_by_id(data.issue_comments, issue_comments)
            _append_unique_by_id(data.review_comments, review_comments)

        # 5. Review comments — fetch from recent PR-related events
        # Use the events API to find IssueCommentEvent and PullRequestReviewCommentEvent
        events = await _get(
            client,
            f"/users/{username}/events",
            params={"per_page": "100"},
        )
        if events:
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
        )
        if reviewed_pr_items:
            authored_prs = {
                identity for pr in data.pull_requests if (identity := _pr_identity(pr)) is not None
            }
            reviewed_prs = [
                pr
                for pr in reviewed_pr_items
                if (identity := _pr_identity(pr)) is not None and identity not in authored_prs
            ]
            (
                reviewed_issue_threads,
                reviewed_review_threads,
                reviewed_issue_comments,
                reviewed_review_comments,
            ) = await fetch_pr_discussions(client, reviewed_prs, username, max_prs=GITHUB_MAX_PRS)
            data.issue_threads.extend(reviewed_issue_threads)
            data.pr_review_threads.extend(reviewed_review_threads)
            _append_unique_by_id(data.issue_comments, reviewed_issue_comments)
            _append_unique_by_id(data.review_comments, reviewed_review_comments)
            data.pr_commits.extend(
                await fetch_pr_commit_lists(client, reviewed_prs, max_prs=GITHUB_MAX_PRS)
            )
            _append_unique_by_id(
                data.pull_request_reviews,
                await fetch_pr_reviews(client, reviewed_prs, max_prs=GITHUB_MAX_PRS),
            )

    logger.info(
        "Fetched GitHub data for %s: %d repos, %d commits, %d PRs, %d reviews, "
        "%d issue comments, %d PR reviews, %d repo language breakdowns, %d commit diffs, "
        "%d PR review threads, %d issue threads, %d PR commit lists",
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
    )
    return data
