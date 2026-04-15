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

# How many commits to fetch diffs for (top N by file change count)
_COMMIT_DIFF_TOP_N = 20


@dataclass
class GitHubData:
    """Container for all fetched GitHub data for a user."""

    profile: dict[str, Any] = field(default_factory=dict)
    repos: list[dict[str, Any]] = field(default_factory=list)
    commits: list[dict[str, Any]] = field(default_factory=list)
    pull_requests: list[dict[str, Any]] = field(default_factory=list)
    review_comments: list[dict[str, Any]] = field(default_factory=list)
    issue_comments: list[dict[str, Any]] = field(default_factory=list)
    repo_languages: dict[str, dict[str, int]] = field(default_factory=dict)
    # Commit diffs: list of {sha, repo, message, files: [{filename, patch, additions, deletions}]}
    commit_diffs: list[dict[str, Any]] = field(default_factory=list)
    # PR review threads: list of {pr_title, pr_url, thread_comments: [{author, body, ...}]}
    pr_review_threads: list[dict[str, Any]] = field(default_factory=list)
    # Issue threads: list of {title, url, body, comments: [{author, body}]}
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


async def fetch_github_data(username: str) -> GitHubData:
    """Fetch all available GitHub activity for a user."""
    data = GitHubData()

    async with httpx.AsyncClient(
        base_url=API_BASE, headers=_headers(), timeout=30.0
    ) as client:
        # 1. User profile
        profile = await _get(client, f"/users/{username}")
        if profile:
            data.profile = profile

        # 2. Repos — fetch ALL (paginated, up to 300)
        repos = await _get_paginated(
            client,
            f"/users/{username}/repos",
            params={"sort": "pushed", "per_page": "100", "type": "owner"},
            max_pages=3,
        )
        if repos:
            data.repos = repos

            # 2b. Per-repo language breakdown for top 15 repos
            for repo in repos[:15]:
                repo_name = repo.get("full_name") or repo.get("name", "")
                if not repo_name:
                    continue
                langs = await _get(client, f"/repos/{repo_name}/languages")
                if langs and isinstance(langs, dict):
                    data.repo_languages[repo_name] = langs

        # 3. Recent commits (search API) — increased to 200
        commits_resp = await _get(
            client,
            "/search/commits",
            params={
                "q": f"author:{username}",
                "sort": "author-date",
                "per_page": "100",
            },
        )
        if commits_resp and "items" in commits_resp:
            data.commits = commits_resp["items"]

        # 3b. Fetch a second page to get up to 200 commits
        if commits_resp and commits_resp.get("total_count", 0) > 100:
            commits_resp2 = await _get(
                client,
                "/search/commits",
                params={
                    "q": f"author:{username}",
                    "sort": "author-date",
                    "per_page": "100",
                    "page": "2",
                },
            )
            if commits_resp2 and "items" in commits_resp2:
                data.commits.extend(commits_resp2["items"])

        # 3c. Fetch commit diffs for the top N most impactful commits
        data.commit_diffs = await _fetch_commit_diffs(client, username, data.commits)

        # 4. PRs authored — increased to 100
        prs_resp = await _get(
            client,
            "/search/issues",
            params={
                "q": f"author:{username} type:pr",
                "sort": "updated",
                "per_page": "100",
            },
        )
        if prs_resp and "items" in prs_resp:
            data.pull_requests = prs_resp["items"]

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
                        data.review_comments.append(comment)
                elif etype == "IssueCommentEvent":
                    comment = payload.get("comment", {})
                    if comment:
                        data.issue_comments.append(comment)

        # 6. Fetch full PR review threads (inline review comments + discussion) for authored PRs
        data.pr_review_threads = await _fetch_pr_review_threads(
            client, username, data.pull_requests
        )

        # 7. If no review comments from events, try search
        if not data.review_comments:
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
                # Fetch review comments from these PRs
                for pr in review_resp["items"][:5]:
                    pr_url = pr.get("pull_request", {}).get("url", "")
                    if pr_url:
                        comments = await _get(
                            client, f"{pr_url}/comments"
                        )
                        if comments:
                            for c in comments:
                                if (c.get("user", {}).get("login", "")).lower() == username.lower():
                                    data.review_comments.append(c)

        # 8. Fetch issue discussion threads (issues user created or commented on)
        data.issue_threads = await _fetch_issue_threads(client, username)

    logger.info(
        "Fetched GitHub data for %s: %d repos, %d commits, %d commit diffs, %d PRs, "
        "%d pr_review_threads, %d reviews, %d issue comments, %d issue_threads, %d repo language breakdowns",
        username,
        len(data.repos),
        len(data.commits),
        len(data.commit_diffs),
        len(data.pull_requests),
        len(data.pr_review_threads),
        len(data.review_comments),
        len(data.issue_comments),
        len(data.issue_threads),
        len(data.repo_languages),
    )
    return data


async def _fetch_commit_diffs(
    client: httpx.AsyncClient,
    username: str,
    commits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fetch diffs for the most impactful commits (by changed-file count).

    Picks up to _COMMIT_DIFF_TOP_N commits ordered by number of files changed
    (proxy for impact). Falls back to first N if file-count info isn't present
    in the search result.
    """
    if not commits:
        return []

    # Sort by files changed descending (search results include stats only when
    # the full commit object is embedded; otherwise fall back to index order)
    def _impact_score(c: dict) -> int:
        stats = c.get("commit", {}).get("stats", {})
        if stats:
            return stats.get("total", 0)
        # Use additions + deletions from top-level stats if present
        return c.get("stats", {}).get("total", 0)

    sorted_commits = sorted(commits, key=_impact_score, reverse=True)
    candidates = sorted_commits[:_COMMIT_DIFF_TOP_N]

    diffs: list[dict[str, Any]] = []
    for commit in candidates:
        sha = commit.get("sha")
        repo_info = commit.get("repository", {})
        repo_name = repo_info.get("full_name", "")
        if not sha or not repo_name:
            continue

        detail = await _get(client, f"/repos/{repo_name}/commits/{sha}")
        if not detail or not isinstance(detail, dict):
            continue

        files = detail.get("files", [])
        stats = detail.get("stats", {})
        message = detail.get("commit", {}).get("message", "")

        diff_entry: dict[str, Any] = {
            "sha": sha,
            "repo": repo_name,
            "message": message,
            "additions": stats.get("additions", 0),
            "deletions": stats.get("deletions", 0),
            "total_changes": stats.get("total", 0),
            "files": [],
        }

        for f in files[:10]:  # cap at 10 files per commit for token budget
            patch = f.get("patch", "")
            # Truncate very large patches
            if len(patch) > 2000:
                patch = patch[:2000] + "\n... (truncated)"
            diff_entry["files"].append(
                {
                    "filename": f.get("filename", ""),
                    "status": f.get("status", ""),
                    "additions": f.get("additions", 0),
                    "deletions": f.get("deletions", 0),
                    "patch": patch,
                }
            )

        diffs.append(diff_entry)

    return diffs


async def _fetch_pr_review_threads(
    client: httpx.AsyncClient,
    username: str,
    pull_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fetch PR review comment threads for authored PRs.

    For each PR in the list, fetches all review comments (inline code comments
    with replies grouped by thread). Returns structured thread objects that
    capture the full discussion context and tone.
    """
    if not pull_requests:
        return []

    threads: list[dict[str, Any]] = []

    # Process up to 20 PRs — balance coverage vs API budget
    for pr in pull_requests[:20]:
        pr_api_url = pr.get("pull_request", {}).get("url", "")
        if not pr_api_url:
            continue

        pr_title = pr.get("title", "Untitled PR")
        pr_html_url = pr.get("html_url", "")
        pr_body = (pr.get("body") or "").strip()

        # Fetch inline review comments
        review_comments = await _get(client, f"{pr_api_url}/comments")
        # Fetch general PR conversation comments (non-inline)
        issue_comments = await _get(
            client,
            pr_api_url.replace("/pulls/", "/issues/") + "/comments",
        )

        all_review = review_comments if isinstance(review_comments, list) else []
        all_issue = issue_comments if isinstance(issue_comments, list) else []

        if not all_review and not all_issue:
            continue

        thread: dict[str, Any] = {
            "pr_title": pr_title,
            "pr_url": pr_html_url,
            "pr_body_snippet": pr_body[:500] if pr_body else "",
            "review_comments": [],
            "conversation_comments": [],
        }

        for c in all_review[:30]:
            thread["review_comments"].append(
                {
                    "author": (c.get("user") or {}).get("login", "unknown"),
                    "body": (c.get("body") or "").strip(),
                    "path": c.get("path", ""),
                    "diff_hunk": c.get("diff_hunk", ""),
                }
            )

        for c in all_issue[:20]:
            author = (c.get("user") or {}).get("login", "unknown")
            body = (c.get("body") or "").strip()
            if body:
                thread["conversation_comments"].append({"author": author, "body": body})

        threads.append(thread)

    return threads


async def _fetch_issue_threads(
    client: httpx.AsyncClient,
    username: str,
) -> list[dict[str, Any]]:
    """Fetch issue discussion threads the user created or participated in.

    Uses the search API to find:
    1. Issues created by the user (for their writing style & problem framing)
    2. Issues the user commented on (for their collaboration style)

    Returns structured thread objects with title, body, and top comments.
    """
    threads: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    async def _process_issues(issues: list[dict]) -> None:
        for issue in issues[:15]:
            html_url = issue.get("html_url", "")
            if html_url in seen_urls:
                continue
            seen_urls.add(html_url)

            # Skip PRs (search/issues returns both PRs and issues)
            if issue.get("pull_request"):
                continue

            comments_url = issue.get("comments_url", "")
            issue_comments: list[dict] = []
            if comments_url and issue.get("comments", 0) > 0:
                raw = await _get(client, comments_url, params={"per_page": "30"})
                if isinstance(raw, list):
                    issue_comments = raw

            thread: dict[str, Any] = {
                "title": issue.get("title", ""),
                "url": html_url,
                "body": (issue.get("body") or "").strip()[:1000],
                "state": issue.get("state", ""),
                "author": (issue.get("user") or {}).get("login", "unknown"),
                "comments": [],
            }
            for c in issue_comments[:15]:
                author = (c.get("user") or {}).get("login", "unknown")
                body = (c.get("body") or "").strip()
                if body:
                    thread["comments"].append({"author": author, "body": body[:500]})

            threads.append(thread)

    # Issues created by user
    created_resp = await _get(
        client,
        "/search/issues",
        params={
            "q": f"author:{username} type:issue",
            "sort": "updated",
            "per_page": "20",
        },
    )
    if created_resp and "items" in created_resp:
        await _process_issues(created_resp["items"])

    # Issues the user commented on (but didn't create)
    commented_resp = await _get(
        client,
        "/search/issues",
        params={
            "q": f"commenter:{username} type:issue -author:{username}",
            "sort": "updated",
            "per_page": "20",
        },
    )
    if commented_resp and "items" in commented_resp:
        await _process_issues(commented_resp["items"])

    return threads
