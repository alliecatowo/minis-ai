"""GitHub API client for fetching user activity data."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
COMMIT_DIFF_LIMIT = 20
PR_DISCUSSION_LIMIT = 15
PR_DISCUSSION_MAX_PAGES = 2
PR_REVIEW_LIMIT = 15
PR_REVIEW_MAX_PAGES = 2


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


def _headers() -> dict[str, str]:
    # mercy-preview enables topics array on repository objects
    headers = {"Accept": "application/vnd.github.mercy-preview+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> Any:
    """Make a GET request, handling rate limits and errors."""
    resp = await client.get(url, params=params)
    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        logger.warning("GitHub rate limit hit for %s", url)
        return None
    if resp.status_code == 422:
        # GitHub search validation error — skip
        logger.warning("GitHub 422 for %s: %s", url, resp.text[:200])
        return None
    resp.raise_for_status()
    return resp.json()


async def _get_paginated(
    client: httpx.AsyncClient, url: str, params: dict | None = None, max_pages: int = 3
) -> list[dict]:
    """Fetch paginated results, following Link headers up to max_pages."""
    all_items: list[dict] = []
    params = dict(params or {})
    params.setdefault("per_page", "100")

    for _ in range(max_pages):
        resp = await client.get(url, params=params)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            logger.warning("GitHub rate limit hit for %s", url)
            break
        if resp.status_code == 422:
            logger.warning("GitHub 422 for %s: %s", url, resp.text[:200])
            break
        resp.raise_for_status()

        items = resp.json()
        if not isinstance(items, list):
            break
        all_items.extend(items)

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
    max_commits: int = COMMIT_DIFF_LIMIT,
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
    max_prs: int = PR_DISCUSSION_LIMIT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch paginated PR issue discussions and review comment threads.

    Returns ``(issue_threads, review_threads, authored_issue_comments,
    authored_review_comments)``. Thread snapshots preserve public comments on
    selected authored PRs so extraction can use target, audience, and timing.
    """
    issue_threads: list[dict[str, Any]] = []
    review_threads: list[dict[str, Any]] = []
    authored_issue_comments: list[dict[str, Any]] = []
    authored_review_comments: list[dict[str, Any]] = []
    username_lower = username.casefold()

    for pr in pull_requests[:max_prs]:
        number = pr.get("number")
        repo = _repo_full_name_from_pr(pr)
        if not number or not repo:
            continue

        pr_node_id = pr.get("node_id") or f"{repo}#{number}"

        issue_comments = await _get_paginated(
            client,
            f"/repos/{repo}/issues/{number}/comments",
            max_pages=PR_DISCUSSION_MAX_PAGES,
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
            authored_issue_comments.extend(
                c for c in issue_comments if _author_login(c).casefold() == username_lower
            )

        review_comments = await _get_paginated(
            client,
            f"/repos/{repo}/pulls/{number}/comments",
            max_pages=PR_DISCUSSION_MAX_PAGES,
        )
        if review_comments:
            review_threads.extend(
                _group_pr_review_threads(repo, int(number), str(pr_node_id), review_comments)
            )
            authored_review_comments.extend(
                c for c in review_comments if _author_login(c).casefold() == username_lower
            )

    return issue_threads, review_threads, authored_issue_comments, authored_review_comments


async def fetch_pr_reviews(
    client: httpx.AsyncClient,
    pull_requests: list[dict[str, Any]],
    *,
    max_prs: int = PR_REVIEW_LIMIT,
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
            max_pages=PR_REVIEW_MAX_PAGES,
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


_GRAPHQL_REPOS_QUERY = """
query($login: String!) {
  user(login: $login) {
    repositories(first: 30, ownerAffiliations: OWNER,
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
    client: httpx.AsyncClient, username: str, top_n: int = 30
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
        graphql_result = await fetch_user_repos_graphql(client, username)
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
                max_pages=3,
            )
            if repos:
                data.repos = repos

                # Per-repo language breakdown for top 15 repos.
                for repo in repos[:15]:
                    repo_name = repo.get("full_name") or repo.get("name", "")
                    if not repo_name:
                        continue
                    langs = await _get(client, f"/repos/{repo_name}/languages")
                    if langs and isinstance(langs, dict):
                        data.repo_languages[repo_name] = langs

        # 3. Recent commits (search API)
        commits_resp = await _get(
            client,
            "/search/commits",
            params={
                "q": f"author:{username}",
                "sort": "author-date",
                "per_page": "50",
            },
        )
        if commits_resp and "items" in commits_resp:
            data.commits = commits_resp["items"]
            data.commit_diffs = await fetch_commit_diffs(client, data.commits)

        # 4. PRs authored
        prs_resp = await _get(
            client,
            "/search/issues",
            params={
                "q": f"author:{username} type:pr",
                "sort": "updated",
                "per_page": "30",
            },
        )
        if prs_resp and "items" in prs_resp:
            data.pull_requests = prs_resp["items"]
            (
                data.issue_threads,
                data.pr_review_threads,
                authored_issue_comments,
                authored_review_comments,
            ) = await fetch_pr_discussions(client, data.pull_requests, username)
            data.pull_request_reviews = await fetch_pr_reviews(client, data.pull_requests)
            _append_unique_by_id(data.issue_comments, authored_issue_comments)
            _append_unique_by_id(data.review_comments, authored_review_comments)

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
        review_resp = await _get(
            client,
            "/search/issues",
            params={
                "q": f"commenter:{username} type:pr",
                "sort": "updated",
                "per_page": "20",
            },
        )
        if review_resp and "items" in review_resp:
            authored_prs = {
                identity for pr in data.pull_requests if (identity := _pr_identity(pr)) is not None
            }
            reviewed_prs = [
                pr
                for pr in review_resp["items"][:5]
                if (identity := _pr_identity(pr)) is not None and identity not in authored_prs
            ]
            (
                reviewed_issue_threads,
                reviewed_review_threads,
                reviewed_issue_comments,
                reviewed_review_comments,
            ) = await fetch_pr_discussions(client, reviewed_prs, username, max_prs=5)
            data.issue_threads.extend(reviewed_issue_threads)
            data.pr_review_threads.extend(reviewed_review_threads)
            _append_unique_by_id(data.issue_comments, reviewed_issue_comments)
            _append_unique_by_id(data.review_comments, reviewed_review_comments)
            _append_unique_by_id(
                data.pull_request_reviews,
                await fetch_pr_reviews(client, reviewed_prs, max_prs=5),
            )

    logger.info(
        "Fetched GitHub data for %s: %d repos, %d commits, %d PRs, %d reviews, "
        "%d issue comments, %d PR reviews, %d repo language breakdowns, %d commit diffs, "
        "%d PR review threads, %d issue threads",
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
    )
    return data
