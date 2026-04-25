"""GitHub ingestion source plugin — wraps existing github fetch + formatter."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.github import GitHubData, fetch_github_data
from app.plugins.base import EvidenceItem, IngestionSource

logger = logging.getLogger(__name__)


async def _get_cached(
    session: AsyncSession, mini_id: str, source_name: str, data_key: str
) -> Any | None:
    """Check for valid cached data."""
    from app.models.ingestion_data import IngestionData

    result = await session.execute(
        select(IngestionData).where(
            IngestionData.mini_id == mini_id,
            IngestionData.source_name == source_name,
            IngestionData.data_key == data_key,
        )
    )
    cached = result.scalar_one_or_none()
    if cached and cached.expires_at and cached.expires_at > datetime.now(timezone.utc):
        return json.loads(cached.data_json)
    return None


async def _save_cache(
    session: AsyncSession,
    mini_id: str,
    source_name: str,
    data_key: str,
    data: Any,
    ttl_hours: int = 24,
) -> None:
    """Save or update cached data."""
    from app.models.ingestion_data import IngestionData

    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=ttl_hours)

    result = await session.execute(
        select(IngestionData).where(
            IngestionData.mini_id == mini_id,
            IngestionData.source_name == source_name,
            IngestionData.data_key == data_key,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.data_json = json.dumps(data)
        existing.fetched_at = now
        existing.expires_at = expires
    else:
        entry = IngestionData(
            mini_id=mini_id,
            source_name=source_name,
            data_key=data_key,
            data_json=json.dumps(data),
            fetched_at=now,
            expires_at=expires,
        )
        session.add(entry)
    await session.flush()


class GitHubSource(IngestionSource):
    """Ingestion source that fetches GitHub activity for a username."""

    name = "github"

    async def _fetch_with_cache(
        self, identifier: str, mini_id: str, session: AsyncSession
    ) -> GitHubData:
        """Fetch GitHub data, using IngestionData cache where available."""
        # Try loading all cached pieces
        cached_profile = await _get_cached(session, mini_id, "github", "profile")
        cached_repos = await _get_cached(session, mini_id, "github", "repos")
        cached_commits = await _get_cached(session, mini_id, "github", "commits")
        cached_reviews = await _get_cached(session, mini_id, "github", "review_comments")

        # If all cached, reconstruct GitHubData directly
        if all(
            v is not None for v in [cached_profile, cached_repos, cached_commits, cached_reviews]
        ):
            logger.info("Using fully cached GitHub data for %s (mini_id=%s)", identifier, mini_id)
            cached_languages = await _get_cached(session, mini_id, "github", "repo_languages") or {}
            cached_prs = await _get_cached(session, mini_id, "github", "pull_requests") or []
            cached_issue_comments = (
                await _get_cached(session, mini_id, "github", "issue_comments") or []
            )
            cached_commit_diffs = (
                await _get_cached(session, mini_id, "github", "commit_diffs") or []
            )
            cached_pr_review_threads = (
                await _get_cached(session, mini_id, "github", "pr_review_threads") or []
            )
            cached_issue_threads = (
                await _get_cached(session, mini_id, "github", "issue_threads") or []
            )
            return GitHubData(
                profile=cached_profile,
                repos=cached_repos,
                commits=cached_commits,
                pull_requests=cached_prs,
                review_comments=cached_reviews,
                issue_comments=cached_issue_comments,
                repo_languages=cached_languages,
                commit_diffs=cached_commit_diffs,
                pr_review_threads=cached_pr_review_threads,
                issue_threads=cached_issue_threads,
            )

        # Cache miss — fetch fresh and save
        logger.info("Cache miss for %s (mini_id=%s), fetching from GitHub API", identifier, mini_id)
        github_data = await fetch_github_data(identifier)

        # Save each piece with appropriate TTLs
        await _save_cache(session, mini_id, "github", "profile", github_data.profile, ttl_hours=24)
        await _save_cache(session, mini_id, "github", "repos", github_data.repos, ttl_hours=168)
        await _save_cache(session, mini_id, "github", "commits", github_data.commits, ttl_hours=24)
        await _save_cache(
            session, mini_id, "github", "pull_requests", github_data.pull_requests, ttl_hours=24
        )
        await _save_cache(
            session, mini_id, "github", "review_comments", github_data.review_comments, ttl_hours=24
        )
        await _save_cache(
            session, mini_id, "github", "issue_comments", github_data.issue_comments, ttl_hours=24
        )
        await _save_cache(
            session, mini_id, "github", "repo_languages", github_data.repo_languages, ttl_hours=168
        )
        await _save_cache(
            session, mini_id, "github", "commit_diffs", github_data.commit_diffs, ttl_hours=24
        )
        await _save_cache(
            session,
            mini_id,
            "github",
            "pr_review_threads",
            github_data.pr_review_threads,
            ttl_hours=24,
        )
        await _save_cache(
            session, mini_id, "github", "issue_threads", github_data.issue_threads, ttl_hours=24
        )

        return github_data

    async def fetch_items(
        self,
        identifier: str,
        mini_id: str,
        session: AsyncSession | None,
        *,
        since_external_ids: set[str] | None = None,
    ) -> AsyncIterator[EvidenceItem]:
        """Yield one EvidenceItem per GitHub entity (commit, PR, review, issue comment).

        Uses the same cached GitHubData as ``_fetch_with_cache()`` so no additional
        API calls are made when the cache is warm.  Items whose external_id already appears in
        ``since_external_ids`` are skipped (incremental-fetch fast path).

        external_id shapes:
          - ``commit:{sha}``
          - ``commit_diff:{sha}``
          - ``pr:{owner}/{repo}#{number}``
          - ``review:{pr_node_id}#{review_id}``
          - ``pr_review_thread:{owner}/{repo}#{number}:{thread_id}@{latest_comment_id}``
          - ``issue_comment:{comment_id}``
          - ``issue_thread:{owner}/{repo}#{number}@{latest_comment_id}``
        """
        since = since_external_ids or set()

        if session is not None:
            github_data = await self._fetch_with_cache(identifier, mini_id, session)
        else:
            github_data = await fetch_github_data(identifier)

        # ── Commits ─────────────────────────────────────────────────────────
        for commit in github_data.commits:
            sha = commit.get("sha") or commit.get("commit", {}).get("sha") or ""
            if not sha:
                continue
            external_id = f"commit:{sha}"
            if external_id in since:
                continue
            msg = commit.get("commit", {}).get("message") or commit.get("message") or ""
            author = (
                commit.get("author", {}).get("login")
                or commit.get("committer", {}).get("login")
                or commit.get("commit", {}).get("author", {}).get("name")
                or ""
            )
            author_name = (
                commit.get("commit", {}).get("author", {}).get("name")
                or ""
            )
            repo_name = commit.get("repository", {}).get("full_name", "")
            content_parts = [f"Commit: {sha[:12]}"]
            if repo_name:
                content_parts.append(f"Repository: {repo_name}")
            if author_name or author:
                content_parts.append(f"Author: {author_name or author}")
            content_parts.append(f"Message:\n{msg}")

            # Attach diff summary if available
            for diff in github_data.commit_diffs:
                if diff.get("sha") == sha:
                    files = diff.get("files", [])
                    if files:
                        changed = [f.get("filename", "") for f in files[:10]]
                        content_parts.append(f"Files changed: {', '.join(changed)}")
                    break

            date_str = commit.get("commit", {}).get("author", {}).get("date") or commit.get("commit", {}).get("committer", {}).get("date")
            evidence_date = _parse_github_date(date_str)

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="commit",
                content="\n".join(content_parts),
                context="commit_message",
                evidence_date=evidence_date,
                source_uri=commit.get("html_url"),
                author_id=author,
                scope={"type": "repo", "id": repo_name, "commit": sha} if repo_name else None,
                raw_body=msg,
                raw_body_ref=f"github:commit:{sha}",
                raw_context={
                    "ref": f"github:commit/{repo_name}/{sha}" if repo_name else f"github:commit/{sha}",
                    "message": msg,
                },
                provenance={
                    "collector": "github",
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.95 if author else 0.75,
                },
                metadata={
                    "sha": sha,
                    "repo": repo_name,
                    "author": author,
                    "author_name": author_name,
                },
                privacy="public",
            )

        # ── Commit Diffs ────────────────────────────────────────────────────
        for diff in github_data.commit_diffs:
            sha = diff.get("sha") or ""
            if not sha:
                continue
            external_id = f"commit_diff:{sha}"
            if external_id in since:
                continue

            repo_name = diff.get("repo") or diff.get("repository", {}).get("full_name", "")
            files = diff.get("files") or []
            message = diff.get("commit", {}).get("message") or ""
            author = (
                (diff.get("author") or {}).get("login")
                or diff.get("commit", {}).get("author", {}).get("name")
                or ""
            )
            date_str = (
                diff.get("commit", {}).get("author", {}).get("date")
                or diff.get("commit", {}).get("committer", {}).get("date")
            )
            file_metadata = [_file_metadata(file) for file in files]

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="commit_diff",
                content=_format_commit_diff(diff),
                context="code_change",
                evidence_date=_parse_github_date(date_str),
                source_uri=diff.get("html_url"),
                author_id=author,
                scope={"type": "repo", "id": repo_name, "commit": sha} if repo_name else None,
                raw_body=message,
                raw_body_ref=f"github:commit_diff:{sha}",
                raw_context={
                    "ref": (
                        f"github:commit_diff/{repo_name}/{sha}"
                        if repo_name
                        else f"github:commit_diff/{sha}"
                    ),
                    "stats": diff.get("stats") or {},
                    "files": file_metadata,
                },
                provenance={
                    "collector": "github",
                    "github_api": "repos.commits.get",
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.95 if author else 0.8,
                },
                metadata={
                    "sha": sha,
                    "repo": repo_name,
                    "author": author,
                    "html_url": diff.get("html_url"),
                    "files": file_metadata,
                    "stats": diff.get("stats") or {},
                },
                privacy="public",
            )

        # ── Pull Requests ────────────────────────────────────────────────────
        for pr in github_data.pull_requests:
            number = pr.get("number")
            repo = _repo_from_pr(pr)
            if not number:
                continue
            external_id = f"pr:{repo}#{number}"
            if external_id in since:
                continue
            title = pr.get("title") or ""
            body = pr.get("body") or ""
            state = pr.get("state") or ""
            author = pr.get("user", {}).get("login") or ""
            content_parts = [
                f"Pull Request #{number}: {title}",
                f"Repository: {repo}",
                f"State: {state}",
            ]
            if body:
                content_parts.append(f"Description:\n{body[:2000]}")

            # Attach review thread data if available
            pr_node_id = pr.get("node_id") or str(number)
            for thread in github_data.pr_review_threads:
                if thread.get("pr_number") == number or thread.get("pr_node_id") == pr_node_id:
                    comments = thread.get("comments", [])
                    if comments:
                        thread_text = "\n".join(
                            f"  [{(c.get('user') or {}).get('login', '?')}]: {c.get('body', '')[:300]}"
                            for c in comments[:5]
                        )
                        content_parts.append(f"Review thread:\n{thread_text}")
                    break

            date_str = pr.get("created_at") or pr.get("updated_at")
            evidence_date = _parse_github_date(date_str)

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="pr",
                content="\n".join(content_parts),
                context="issue_discussion",
                evidence_date=evidence_date,
                source_uri=pr.get("html_url"),
                author_id=author,
                target_id=f"github:{repo}#{number}" if repo else None,
                scope={"type": "repo", "id": repo, "pr_number": number} if repo else None,
                raw_body=body,
                raw_body_ref=f"github:pull_request:{repo}#{number}" if repo else None,
                raw_context={
                    "ref": f"github:pull_request/{repo}/{number}" if repo else f"github:pull_request/{number}",
                    "state": state,
                    "title": title,
                },
                provenance={
                    "collector": "github",
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.9 if author else 0.7,
                },
                metadata={
                    "number": number,
                    "repo": repo,
                    "state": state,
                    "author": author,
                },
                privacy="public",
            )

        # ── PR Review Threads ────────────────────────────────────────────────
        for thread in github_data.pr_review_threads:
            thread_id = thread.get("thread_id")
            repo = thread.get("repo") or ""
            pr_number = thread.get("pr_number")
            if not thread_id or not repo or not pr_number:
                continue
            comments = thread.get("comments") or []
            latest_comment_id = _latest_comment_id(comments)
            external_id = f"pr_review_thread:{thread_id}@{latest_comment_id}"
            if external_id in since:
                continue

            first_comment = comments[0] if comments else {}
            authors = _comment_authors(comments)
            authored_comment_ids = [
                c.get("id")
                for c in comments
                if identifier
                and ((c.get("user") or {}).get("login") or "").casefold() == identifier.casefold()
            ]
            date_str = first_comment.get("created_at")
            path = thread.get("path") or ""
            line = thread.get("line") or thread.get("original_line")

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="pr_review_thread",
                content=_format_pr_review_thread(thread),
                context="code_review",
                evidence_date=_parse_github_date(date_str),
                source_uri=first_comment.get("html_url"),
                author_id=(first_comment.get("user") or {}).get("login"),
                target_id=_review_target_id(repo, pr_number, path, line),
                scope=_review_scope(repo, pr_number, path, line, thread.get("side")),
                raw_body=_thread_raw_body(comments),
                raw_body_ref=f"github:pr_review_thread:{thread_id}@{latest_comment_id}",
                raw_context={
                    "ref": f"github:pr_review_thread/{thread_id}",
                    "thread_id": thread_id,
                    "pr_node_id": thread.get("pr_node_id"),
                    "diff_hunk": thread.get("diff_hunk") or "",
                    "comment_ids": [c.get("id") for c in comments if c.get("id") is not None],
                },
                provenance={
                    "collector": "github",
                    "github_api": "repos.pulls.listReviewComments",
                    "thread_snapshot": True,
                    "authored_by_subject": bool(authored_comment_ids),
                    "authored_comment_ids": authored_comment_ids,
                    "confidence": 0.95 if comments else 0.7,
                },
                metadata={
                    "repo": repo,
                    "pr_number": pr_number,
                    "thread_id": thread_id,
                    "path": path,
                    "line": thread.get("line"),
                    "original_line": thread.get("original_line"),
                    "start_line": thread.get("start_line"),
                    "side": thread.get("side"),
                    "comment_ids": [c.get("id") for c in comments if c.get("id") is not None],
                    "authors": authors,
                },
                privacy="public",
            )

        # ── Reviews ──────────────────────────────────────────────────────────
        for review in github_data.review_comments:
            review_id = review.get("id")
            pr_id = (
                review.get("pull_request_review_id")
                or review.get("pull_request_url", "").split("/")[-1]
                or "0"
            )
            if not review_id:
                continue
            external_id = f"review:{pr_id}#{review_id}"
            if external_id in since:
                continue
            body = review.get("body") or ""
            path = review.get("path") or ""
            diff_hunk = review.get("diff_hunk") or ""
            author = review.get("user", {}).get("login") or ""
            repo = _repo_from_review_comment(review)
            pr_number = _pr_number_from_review_comment(review)
            line = review.get("line") or review.get("original_line")
            side = review.get("side")
            content_parts = [f"Review comment (id={review_id})"]
            if repo:
                content_parts.append(f"Repository: {repo}")
            if pr_number:
                content_parts.append(f"Pull Request: #{pr_number}")
            if author:
                content_parts.append(f"Author: {author}")
            if path:
                content_parts.append(f"File: {path}")
            if line:
                line_context = f"Line: {line}"
                if side:
                    line_context += f" ({side})"
                content_parts.append(line_context)
            if body:
                content_parts.append(f"Comment:\n{body[:1000]}")
            if diff_hunk:
                content_parts.append(f"Diff context:\n{diff_hunk[:500]}")

            date_str = review.get("submitted_at") or review.get("created_at") or review.get("updated_at")
            evidence_date = _parse_github_date(date_str)

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="review",
                content="\n".join(content_parts),
                context="code_review",
                evidence_date=evidence_date,
                source_uri=review.get("html_url"),
                author_id=author,
                target_id=_review_target_id(repo, pr_number, path, line),
                scope=_review_scope(repo, pr_number, path, line, side),
                raw_body=body,
                raw_body_ref=f"github:pull_request_review_comment:{review_id}",
                raw_context={
                    "ref": f"github:pull_request_review_comment/{review_id}",
                    "diff_hunk": diff_hunk,
                    "in_reply_to_id": review.get("in_reply_to_id"),
                    "pull_request_review_id": review.get("pull_request_review_id"),
                },
                provenance={
                    "collector": "github",
                    "github_api": "pull_request_review_comment",
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.95 if author else 0.75,
                },
                metadata={
                    "review_id": review_id,
                    "pr_id": str(pr_id),
                    "repo": repo,
                    "pr_number": pr_number,
                    "path": path,
                    "author": author,
                    "line": review.get("line"),
                    "original_line": review.get("original_line"),
                    "start_line": review.get("start_line"),
                    "side": side,
                    "in_reply_to_id": review.get("in_reply_to_id"),
                    "pull_request_review_id": review.get("pull_request_review_id"),
                    "html_url": review.get("html_url"),
                },
                privacy="public",
            )

        # ── Issue Comments ────────────────────────────────────────────────────
        for comment in github_data.issue_comments:
            comment_id = comment.get("id")
            if not comment_id:
                continue
            external_id = f"issue_comment:{comment_id}"
            if external_id in since:
                continue
            body = comment.get("body") or ""
            issue_url = comment.get("issue_url") or comment.get("html_url") or ""
            author = comment.get("user", {}).get("login") or ""
            repo = _repo_from_issue_url(issue_url)
            issue_number = _issue_number_from_issue_url(issue_url)
            content_parts = [f"Issue comment (id={comment_id})"]
            if issue_url:
                content_parts.append(f"Issue: {issue_url}")
            if author:
                content_parts.append(f"Author: {author}")
            if body:
                content_parts.append(f"Comment:\n{body[:1000]}")

            date_str = comment.get("created_at") or comment.get("updated_at")
            evidence_date = _parse_github_date(date_str)

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="issue_comment",
                content="\n".join(content_parts),
                context="issue_discussion",
                evidence_date=evidence_date,
                source_uri=comment.get("html_url"),
                author_id=author,
                target_id=f"github:{repo}#{issue_number}" if repo and issue_number else None,
                scope=(
                    {"type": "repo", "id": repo, "issue_number": issue_number}
                    if repo and issue_number
                    else None
                ),
                raw_body=body,
                raw_body_ref=f"github:issue_comment:{comment_id}",
                raw_context={
                    "ref": f"github:issue_comment/{comment_id}",
                    "issue_url": issue_url,
                },
                provenance={
                    "collector": "github",
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.95 if author else 0.75,
                },
                metadata={"comment_id": comment_id, "author": author},
                privacy="public",
            )

        # ── Issue / PR Discussion Threads ───────────────────────────────────
        for thread in github_data.issue_threads:
            repo = thread.get("repo") or ""
            pr_number = thread.get("pr_number")
            if not repo or not pr_number:
                continue
            comments = thread.get("comments") or []
            latest_comment_id = _latest_comment_id(comments)
            external_id = f"issue_thread:{repo}#{pr_number}@{latest_comment_id}"
            if external_id in since:
                continue

            first_comment = comments[0] if comments else {}
            authors = _comment_authors(comments)
            authored_comment_ids = [
                c.get("id")
                for c in comments
                if identifier
                and ((c.get("user") or {}).get("login") or "").casefold() == identifier.casefold()
            ]
            date_str = first_comment.get("created_at")

            yield EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="issue_thread",
                content=_format_issue_thread(thread),
                context="issue_discussion",
                evidence_date=_parse_github_date(date_str),
                source_uri=thread.get("html_url") or first_comment.get("html_url"),
                author_id=(first_comment.get("user") or {}).get("login"),
                target_id=f"github:{repo}#{pr_number}",
                scope={"type": "repo", "id": repo, "pr_number": pr_number},
                raw_body=_thread_raw_body(comments),
                raw_body_ref=f"github:issue_thread:{repo}#{pr_number}@{latest_comment_id}",
                raw_context={
                    "ref": f"github:issue_thread/{repo}/{pr_number}",
                    "pr_node_id": thread.get("pr_node_id"),
                    "comment_ids": [c.get("id") for c in comments if c.get("id") is not None],
                },
                provenance={
                    "collector": "github",
                    "github_api": "repos.issues.listComments",
                    "thread_snapshot": True,
                    "authored_by_subject": bool(authored_comment_ids),
                    "authored_comment_ids": authored_comment_ids,
                    "confidence": 0.95 if comments else 0.7,
                },
                metadata={
                    "repo": repo,
                    "pr_number": pr_number,
                    "pr_node_id": thread.get("pr_node_id"),
                    "html_url": thread.get("html_url"),
                    "comment_ids": [c.get("id") for c in comments if c.get("id") is not None],
                    "authors": authors,
                },
                privacy="public",
            )


def _repo_from_pr(pr: dict[str, Any]) -> str:
    base_repo = (pr.get("base") or {}).get("repo") or {}
    if base_repo.get("full_name"):
        return str(base_repo["full_name"])
    repo = pr.get("repo")
    if isinstance(repo, str):
        return repo
    if isinstance(repo, dict) and repo.get("full_name"):
        return str(repo["full_name"])
    repository_url = pr.get("repository_url") or ""
    if "/repos/" in repository_url:
        return repository_url.rsplit("/repos/", 1)[1]
    return ""


def _file_metadata(file: dict[str, Any]) -> dict[str, Any]:
    return {
        "filename": file.get("filename"),
        "status": file.get("status"),
        "additions": file.get("additions"),
        "deletions": file.get("deletions"),
        "changes": file.get("changes"),
    }


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _latest_comment_id(comments: list[dict[str, Any]]) -> str:
    if not comments:
        return "empty"
    latest = max(comments, key=lambda c: c.get("created_at") or "")
    return str(latest.get("id") or "unknown")


def _comment_authors(comments: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            (comment.get("user") or {}).get("login")
            for comment in comments
            if (comment.get("user") or {}).get("login")
        }
    )


def _thread_raw_body(comments: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"[{comment.get('created_at') or ''}] "
        f"{(comment.get('user') or {}).get('login') or 'unknown'}:\n"
        f"{comment.get('body') or ''}"
        for comment in comments
    )


def _format_commit_diff(diff: dict[str, Any]) -> str:
    sha = diff.get("sha") or ""
    repo = diff.get("repo") or diff.get("repository", {}).get("full_name") or ""
    message = diff.get("commit", {}).get("message") or ""
    stats = diff.get("stats") or {}
    files = diff.get("files") or []

    parts = [f"Commit diff: {sha[:12]}"]
    if repo:
        parts.append(f"Repository: {repo}")
    if stats:
        parts.append(
            "Stats: "
            f"+{stats.get('additions', 0)} "
            f"-{stats.get('deletions', 0)} "
            f"({stats.get('total', 0)} total)"
        )
    if message:
        parts.append(f"Message:\n{_truncate(message, 1200)}")

    for file in files[:12]:
        filename = file.get("filename") or "unknown"
        status = file.get("status") or "modified"
        parts.append(
            "\n".join(
                [
                    f"File: {filename}",
                    f"Status: {status}",
                    (
                        f"Changes: +{file.get('additions', 0)} "
                        f"-{file.get('deletions', 0)} "
                        f"({file.get('changes', 0)} total)"
                    ),
                ]
            )
        )
        patch = file.get("patch") or ""
        if patch:
            parts.append(f"Patch:\n{_truncate(patch, 2500)}")

    if len(files) > 12:
        parts.append(f"... {len(files) - 12} additional files omitted from content")

    return "\n".join(parts)


def _format_pr_review_thread(thread: dict[str, Any]) -> str:
    repo = thread.get("repo") or ""
    pr_number = thread.get("pr_number")
    path = thread.get("path") or ""
    line = thread.get("line") or thread.get("original_line")
    side = thread.get("side")
    comments = thread.get("comments") or []

    parts = [f"PR review thread: {repo}#{pr_number}"]
    if path:
        target = f"Target: {path}"
        if line:
            target += f":{line}"
        if side:
            target += f" ({side})"
        parts.append(target)
    diff_hunk = thread.get("diff_hunk") or ""
    if diff_hunk:
        parts.append(f"Diff context:\n{_truncate(diff_hunk, 1000)}")

    for comment in comments[:20]:
        author = (comment.get("user") or {}).get("login") or "unknown"
        created_at = comment.get("created_at") or ""
        body = comment.get("body") or ""
        reply = comment.get("in_reply_to_id")
        prefix = f"[{created_at}] {author}"
        if reply:
            prefix += f" replying to {reply}"
        parts.append(f"{prefix}:\n{_truncate(body, 1200)}")

    if len(comments) > 20:
        parts.append(f"... {len(comments) - 20} additional comments omitted from content")

    return "\n\n".join(parts)


def _format_issue_thread(thread: dict[str, Any]) -> str:
    repo = thread.get("repo") or ""
    pr_number = thread.get("pr_number")
    comments = thread.get("comments") or []

    parts = [f"Issue/PR discussion thread: {repo}#{pr_number}"]
    if thread.get("html_url"):
        parts.append(f"PR: {thread['html_url']}")

    for comment in comments[:30]:
        author = (comment.get("user") or {}).get("login") or "unknown"
        created_at = comment.get("created_at") or ""
        body = comment.get("body") or ""
        parts.append(f"[{created_at}] {author}:\n{_truncate(body, 1200)}")

    if len(comments) > 30:
        parts.append(f"... {len(comments) - 30} additional comments omitted from content")

    return "\n\n".join(parts)


def _repo_from_review_comment(review: dict[str, Any]) -> str:
    pull_request_url = review.get("pull_request_url") or ""
    if "/repos/" not in pull_request_url:
        return ""
    repo_and_tail = pull_request_url.rsplit("/repos/", 1)[1]
    parts = repo_and_tail.split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return ""


def _pr_number_from_review_comment(review: dict[str, Any]) -> int | None:
    pull_request_url = review.get("pull_request_url") or ""
    try:
        return int(pull_request_url.rstrip("/").rsplit("/", 1)[-1])
    except (TypeError, ValueError):
        return None


def _repo_from_issue_url(issue_url: str) -> str:
    if "/repos/" in issue_url:
        repo_and_tail = issue_url.rsplit("/repos/", 1)[1]
    elif "github.com/" in issue_url:
        repo_and_tail = issue_url.rsplit("github.com/", 1)[1]
    else:
        return ""
    parts = repo_and_tail.split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return ""


def _issue_number_from_issue_url(issue_url: str) -> int | None:
    try:
        return int(issue_url.rstrip("/").rsplit("/", 1)[-1])
    except (TypeError, ValueError):
        return None


def _review_target_id(
    repo: str,
    pr_number: int | str | None,
    path: str,
    line: int | str | None,
) -> str | None:
    if not repo or not pr_number:
        return None
    target = f"github:{repo}#{pr_number}"
    if path:
        target += f":{path}"
    if line:
        target += f":{line}"
    return target


def _review_scope(
    repo: str,
    pr_number: int | str | None,
    path: str,
    line: int | str | None,
    side: str | None,
) -> dict[str, Any] | None:
    if not repo:
        return None
    scope: dict[str, Any] = {"type": "repo", "id": repo}
    if pr_number:
        scope["pr_number"] = pr_number
    if path:
        scope["path"] = path
    if line:
        scope["line"] = line
    if side:
        scope["side"] = side
    return scope


def _parse_github_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        if date_str.endswith("Z"):
            date_str = date_str[:-1] + "+00:00"
        return datetime.fromisoformat(date_str).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None

def _aggregate_languages(github_data: GitHubData) -> dict[str, int]:
    """Aggregate language byte counts across all repos into a sorted summary."""
    totals: dict[str, int] = {}
    for lang_map in github_data.repo_languages.values():
        for lang, byte_count in lang_map.items():
            totals[lang] = totals.get(lang, 0) + byte_count
    # Sort by bytes descending
    return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))


def _aggregate_primary_languages(github_data: GitHubData) -> dict[str, int]:
    """Count repos by their primary language across ALL repos."""
    counts: dict[str, int] = {}
    for repo in github_data.repos:
        lang = repo.get("language")
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))
