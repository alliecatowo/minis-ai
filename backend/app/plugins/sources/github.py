"""GitHub ingestion source plugin — wraps existing github fetch + formatter."""

from __future__ import annotations

import json
import logging
from hashlib import sha1
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.ingestion.delta import get_latest_external_ids
from app.ingestion.github import (
    GitHubData,
    _repo_allowed_by_org_policy,
    build_repo_activity_summary,
    classify_recency_window,
    fetch_github_data,
)
from app.plugins.base import EvidenceItem, IngestionSource

logger = logging.getLogger(__name__)
MAX_PR_BODY_CHARS = 8000
MAX_DIFF_HUNK_CHARS = 4000
MID_WINDOW_KEEP_RATIO = 0.5
HISTORICAL_WINDOW_KEEP_RATIO = 0.25
MIN_EVIDENCE_PER_NON_TRIVIAL_REPO = 5
REPO_SCOPED_ITEM_TYPES = {
    "commit",
    "commit_diff",
    "issue",
    "pr",
    "pr_commits",
    "review_authored",
    "review_comment_inline",
    "starred",
    "watched",
    "commit_comment",
    "timeline_event",
    "pr_review_thread",
    "pr_review",
    "review",
    "issue_comment",
    "issue_thread",
    "discussion",
}


def _repo_visibility_from_repo(repo: dict[str, Any]) -> str:
    visibility = str(repo.get("visibility") or "").strip().lower()
    if visibility in {"public", "private", "internal"}:
        return visibility
    if repo.get("private") is True:
        return "private"
    return "public"


def _build_repo_visibility_index(github_data: GitHubData) -> dict[str, str]:
    visibility_by_repo: dict[str, str] = {}
    for repo in github_data.repos:
        full_name = str(repo.get("full_name") or repo.get("name") or "").strip()
        if not full_name:
            continue
        visibility_by_repo[full_name] = _repo_visibility_from_repo(repo)
    for repo_list in (github_data.starred_repos, github_data.watched_repos):
        for repo in repo_list:
            full_name = str(repo.get("full_name") or "").strip()
            if not full_name or full_name in visibility_by_repo:
                continue
            visibility_by_repo[full_name] = _repo_visibility_from_repo(repo)
    return visibility_by_repo


def _normalize_repo_name(repo_name: str | None) -> str:
    return str(repo_name or "").strip()


def _resolve_item_repo(item: EvidenceItem) -> str:
    repo = _repo_for_item(item)
    if repo:
        if "/" not in repo and item.scope:
            owner = item.scope.get("owner")
            if isinstance(owner, str) and owner:
                return f"{owner}/{repo}"
        return _normalize_repo_name(repo)
    if item.scope:
        owner = item.scope.get("owner")
        repo_name = item.scope.get("repo")
        if isinstance(owner, str) and isinstance(repo_name, str) and owner and repo_name:
            return f"{owner}/{repo_name}"
        for key in ("repo", "repo_name"):
            value = item.scope.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _classify_access_for_repo(
    repo_name: str,
    identifier: str,
    repo_visibility_index: dict[str, str],
) -> tuple[str, str]:
    visibility = repo_visibility_index.get(repo_name)
    if visibility is None:
        owner = repo_name.split("/", 1)[0].casefold() if "/" in repo_name else ""
        subject = identifier.casefold()
        # Conservative default for authenticated, non-owned repos whose
        # visibility isn't in our index: avoid classifying as public.
        if settings.github_token and owner and owner != subject:
            return "private", "company"
        return "public", "public"
    if visibility == "public":
        return "public", "public"

    owner = repo_name.split("/", 1)[0].casefold() if "/" in repo_name else ""
    subject = identifier.casefold()
    if visibility == "private" and owner == subject:
        return "private", "private"
    return "private", "company"


def _apply_access_controls(
    item: EvidenceItem,
    *,
    identifier: str,
    repo_visibility_index: dict[str, str],
) -> EvidenceItem:
    repo_name = _resolve_item_repo(item)
    if repo_name:
        privacy, access_classification = _classify_access_for_repo(
            repo_name,
            identifier,
            repo_visibility_index,
        )
        item.privacy = privacy
        item.access_classification = access_classification
    else:
        item.access_classification = item.access_classification or item.privacy
    item.source_authorization = "authorized"
    return item


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
        cached_issues = await _get_cached(session, mini_id, "github", "issues")
        cached_reviews = await _get_cached(session, mini_id, "github", "review_comments")
        cached_pull_request_reviews = await _get_cached(
            session, mini_id, "github", "pull_request_reviews"
        )

        # If all cached, reconstruct GitHubData directly
        if all(
            v is not None
            for v in [
                cached_profile,
                cached_repos,
                cached_commits,
                cached_issues,
                cached_reviews,
                cached_pull_request_reviews,
            ]
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
            cached_pr_commits = (
                await _get_cached(session, mini_id, "github", "pr_commits") or []
            )
            cached_reviews_authored = (
                await _get_cached(session, mini_id, "github", "reviews_authored") or []
            )
            cached_inline_review_comments = (
                await _get_cached(session, mini_id, "github", "inline_review_comments") or []
            )
            cached_starred_repos = (
                await _get_cached(session, mini_id, "github", "starred_repos") or []
            )
            cached_watched_repos = (
                await _get_cached(session, mini_id, "github", "watched_repos") or []
            )
            cached_commit_comments = (
                await _get_cached(session, mini_id, "github", "commit_comments") or []
            )
            cached_timeline_events = (
                await _get_cached(session, mini_id, "github", "timeline_events") or []
            )
            cached_stop_reasons = (
                await _get_cached(session, mini_id, "github", "stop_reasons") or []
            )
            cached_gists = await _get_cached(session, mini_id, "github", "gists") or []
            return GitHubData(
                profile=cached_profile,
                repos=cached_repos,
                commits=cached_commits,
                issues=cached_issues,
                pull_requests=cached_prs,
                review_comments=cached_reviews,
                issue_comments=cached_issue_comments,
                pull_request_reviews=cached_pull_request_reviews,
                repo_languages=cached_languages,
                commit_diffs=cached_commit_diffs,
                pr_review_threads=cached_pr_review_threads,
                issue_threads=cached_issue_threads,
                pr_commits=cached_pr_commits,
                reviews_authored=cached_reviews_authored,
                inline_review_comments=cached_inline_review_comments,
                starred_repos=cached_starred_repos,
                watched_repos=cached_watched_repos,
                commit_comments=cached_commit_comments,
                timeline_events=cached_timeline_events,
                stop_reasons=cached_stop_reasons,
                gists=cached_gists,
            )

        # Cache miss — fetch fresh and save
        logger.info("Cache miss for %s (mini_id=%s), fetching from GitHub API", identifier, mini_id)
        github_data = await fetch_github_data(identifier)

        # Save each piece with appropriate TTLs
        await _save_cache(session, mini_id, "github", "profile", github_data.profile, ttl_hours=24)
        await _save_cache(session, mini_id, "github", "repos", github_data.repos, ttl_hours=168)
        await _save_cache(session, mini_id, "github", "commits", github_data.commits, ttl_hours=24)
        await _save_cache(session, mini_id, "github", "issues", github_data.issues, ttl_hours=24)
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
            session,
            mini_id,
            "github",
            "pull_request_reviews",
            github_data.pull_request_reviews,
            ttl_hours=24,
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
        await _save_cache(
            session, mini_id, "github", "pr_commits", github_data.pr_commits, ttl_hours=24
        )
        await _save_cache(
            session, mini_id, "github", "reviews_authored", github_data.reviews_authored, ttl_hours=24
        )
        await _save_cache(
            session,
            mini_id,
            "github",
            "inline_review_comments",
            github_data.inline_review_comments,
            ttl_hours=24,
        )
        await _save_cache(
            session, mini_id, "github", "starred_repos", github_data.starred_repos, ttl_hours=24
        )
        await _save_cache(
            session, mini_id, "github", "watched_repos", github_data.watched_repos, ttl_hours=24
        )
        await _save_cache(
            session,
            mini_id,
            "github",
            "commit_comments",
            github_data.commit_comments,
            ttl_hours=24,
        )
        await _save_cache(
            session,
            mini_id,
            "github",
            "timeline_events",
            github_data.timeline_events,
            ttl_hours=24,
        )
        await _save_cache(
            session, mini_id, "github", "stop_reasons", github_data.stop_reasons, ttl_hours=24
        )
        await _save_cache(session, mini_id, "github", "gists", github_data.gists, ttl_hours=24)

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
          - ``commit:{owner}/{repo}@{sha}``
          - ``commit_diff:{owner}/{repo}@{sha}`` (falls back to ``commit_diff:{sha}`` when repo unknown)
          - ``pr:{owner}/{repo}#{number}``
          - ``review:{owner}/{repo}#{number}/{review_id}``
          - ``inline_comment:{owner}/{repo}#{number}/{comment_id}``
          - ``starred:{owner}/{repo}``
          - ``gist:{id}``
          - ``pr_review:{owner}/{repo}#{number}:{review_id}``
          - ``pr_review_thread:{owner}/{repo}#{number}:{thread_id}@{latest_comment_id}``
          - ``pr_commits:{owner}/{repo}#{number}``
          - ``issue_comment:{comment_id}``
          - ``issue_thread:{owner}/{repo}#{number}@{latest_comment_id}``
        """
        if since_external_ids is not None:
            since = since_external_ids
        elif session is not None:
            since = await get_latest_external_ids(session, mini_id, self.name)
        else:
            since = set()
        collected_items: list[EvidenceItem] = []

        if session is not None:
            github_data = await self._fetch_with_cache(identifier, mini_id, session)
        else:
            github_data = await fetch_github_data(identifier)

        repo_activity = build_repo_activity_summary(github_data)
        repo_visibility_index = _build_repo_visibility_index(github_data)
        language_diversity_item = _build_language_diversity_item(github_data)
        if language_diversity_item is not None:
            collected_items.append(language_diversity_item)
        commit_diffs_by_sha = {
            str(diff.get("sha")): diff
            for diff in github_data.commit_diffs
            if diff.get("sha")
        }
        commit_count_by_repo: dict[str, int] = {}
        issue_count_by_repo: dict[str, int] = {}

        # ── Commits ─────────────────────────────────────────────────────────
        for commit in github_data.commits:
            sha = commit.get("sha") or commit.get("commit", {}).get("sha") or ""
            if not sha:
                continue
            repo_name = commit.get("repository", {}).get("full_name", "")
            if not repo_name:
                continue
            count_for_repo = commit_count_by_repo.get(repo_name, 0)
            if count_for_repo >= settings.github_max_commits_per_repo:
                continue
            external_id = f"commit:{repo_name}@{sha}"
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
            content_parts = [f"Commit: {sha[:12]}"]
            content_parts.append(f"Repository: {repo_name}")
            if author_name or author:
                content_parts.append(f"Author: {author_name or author}")
            content_parts.append(f"Message:\n{msg}")

            diff = commit_diffs_by_sha.get(sha)
            files = (diff or {}).get("files") or []
            if files:
                changed = [f.get("filename", "") for f in files[:20] if f.get("filename")]
                if changed:
                    content_parts.append(f"Files changed summary: {', '.join(changed)}")
            diff_hunk_parts: list[str] = []
            for file in files:
                filename = file.get("filename") or "unknown"
                patch = file.get("patch") or ""
                if not patch:
                    continue
                diff_hunk_parts.append(f"File: {filename}\n{patch}")
            diff_hunks = _truncate("\n\n".join(diff_hunk_parts), 8000) if diff_hunk_parts else ""

            date_str = (
                commit.get("commit", {}).get("author", {}).get("date")
                or commit.get("commit", {}).get("committer", {}).get("date")
            )
            evidence_date = _parse_github_date(date_str)

            commit_count_by_repo[repo_name] = count_for_repo + 1
            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="commit",
                content="\n".join(content_parts),
                context="commit_message",
                evidence_date=evidence_date,
                source_uri=commit.get("html_url"),
                author_id=author,
                scope={"type": "repo", "id": repo_name, "commit": sha},
                raw_body=msg,
                raw_body_ref=f"github:commit:{repo_name}@{sha}",
                raw_context={
                    "ref": f"github:commit/{repo_name}/{sha}",
                    "message": msg,
                    "files": [_file_metadata(file) for file in files],
                    "diff_hunks": diff_hunks,
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
            ))

        # ── Commit Diffs ────────────────────────────────────────────────────
        for diff in github_data.commit_diffs:
            sha = diff.get("sha") or ""
            if not sha:
                continue
            repo_name = diff.get("repo") or diff.get("repository", {}).get("full_name", "")
            external_id = f"commit_diff:{repo_name}@{sha}" if repo_name else f"commit_diff:{sha}"
            files = diff.get("files") or []
            message = diff.get("commit", {}).get("message") or ""
            author = (
                (diff.get("author") or {}).get("login")
                or diff.get("commit", {}).get("author", {}).get("name")
                or ""
            )
            if external_id in since:
                continue
            date_str = (
                diff.get("commit", {}).get("author", {}).get("date")
                or diff.get("commit", {}).get("committer", {}).get("date")
            )
            file_metadata = [_file_metadata(file) for file in files]

            collected_items.append(EvidenceItem(
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
            ))

        # ── PR Reviews Authored For Others ─────────────────────────────────
        for review in github_data.reviews_authored:
            owner = review.get("owner") or ""
            repo_name = review.get("repo") or ""
            pr_number = review.get("pr_number")
            review_id = review.get("review_id") or ""
            if not owner or not repo_name or not pr_number or not review_id:
                continue
            full_repo = f"{owner}/{repo_name}"
            external_id = f"review:{full_repo}#{pr_number}/{review_id}"
            if external_id in since:
                continue
            review_body = review.get("body") or ""
            state = review.get("state") or ""
            comments = review.get("comments") or []
            reactions = _reaction_counts(review)

            parts = [f"Authored PR review: {full_repo}#{pr_number}", f"State: {state}"]
            if review_body:
                parts.append(f"Review body:\n{_truncate(review_body, 2000)}")
            if reactions:
                parts.append(
                    "Reactions: "
                    f"{reactions.get('total_count', 0)} total "
                    f"(+1={reactions.get('+1', 0)}, heart={reactions.get('heart', 0)})"
                )
            for comment in comments:
                if not isinstance(comment, dict):
                    continue
                path = comment.get("path") or ""
                diff_hunk = _truncate(comment.get("diffHunk") or "", MAX_DIFF_HUNK_CHARS)
                body = comment.get("body") or ""
                parts.append(
                    "\n".join(
                        [
                            f"Inline comment file: {path or 'unknown'}",
                            f"Diff hunk:\n{diff_hunk}" if diff_hunk else "Diff hunk: <none>",
                            f"Comment:\n{_truncate(body, 1200)}",
                        ]
                    )
                )

            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="review_authored",
                content="\n\n".join(parts),
                context="code_review",
                evidence_date=_parse_github_date(review.get("submitted_at")),
                source_uri=f"https://github.com/{full_repo}/pull/{pr_number}",
                author_id=identifier,
                target_id=f"github:{full_repo}#{pr_number}",
                scope={
                    "owner": owner,
                    "repo": repo_name,
                    "pr_number": pr_number,
                    "state": state,
                },
                raw_body=review_body,
                raw_body_ref=f"github:review_authored:{full_repo}#{pr_number}/{review_id}",
                raw_context={
                    "ref": f"github:review_authored/{full_repo}/{pr_number}/{review_id}",
                    "comments": comments,
                    "reactions": reactions,
                },
                provenance={
                    "collector": "github",
                    "github_api": "graphql.pullRequestReviewContributions",
                    "authored_by_subject": True,
                    "confidence": 0.95,
                },
                metadata={
                    "owner": owner,
                    "repo": repo_name,
                    "pr_number": pr_number,
                    "review_id": review_id,
                    "state": state,
                    "comment_count": len(comments),
                    "reactions": reactions,
                    "positive_reactions_count": _positive_reaction_count(reactions),
                },
                privacy="public",
            ))

        # ── Inline Review Comments On Authored PRs ─────────────────────────
        for comment in github_data.inline_review_comments:
            comment_id = comment.get("id")
            repo = comment.get("repo") or _repo_from_review_comment(comment)
            pr_number = comment.get("pr_number") or _pr_number_from_review_comment(comment)
            if not comment_id or not repo or not pr_number:
                continue
            external_id = f"inline_comment:{repo}#{pr_number}/{comment_id}"
            if external_id in since:
                continue

            body = comment.get("body") or ""
            path = comment.get("path") or ""
            diff_hunk = _truncate(comment.get("diff_hunk") or "", MAX_DIFF_HUNK_CHARS)
            line = comment.get("line")
            start_line = comment.get("start_line")
            commit_id = comment.get("commit_id")
            author = (comment.get("user") or {}).get("login") or ""
            reactions = _reaction_counts(comment)

            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="review_comment_inline",
                content=body,
                context="code_review",
                evidence_date=_parse_github_date(comment.get("created_at") or comment.get("updated_at")),
                source_uri=comment.get("html_url"),
                author_id=author,
                target_id=_review_target_id(repo, pr_number, path, line),
                scope=_review_scope(repo, pr_number, path, line, comment.get("side")),
                raw_body=body,
                raw_body_ref=f"github:inline_comment:{repo}#{pr_number}/{comment_id}",
                raw_context={
                    "ref": f"github:inline_comment/{repo}/{pr_number}/{comment_id}",
                    "file_path": path,
                    "diff_hunk": diff_hunk,
                    "line": line,
                    "start_line": start_line,
                    "commit_id": commit_id,
                    "reactions": reactions,
                },
                provenance={
                    "collector": "github",
                    "github_api": "repos.pulls.listReviewComments",
                    "confidence": 0.95 if author else 0.75,
                },
                metadata={
                    "file_path": path,
                    "diff_hunk": diff_hunk,
                    "line": line,
                    "start_line": start_line,
                    "commit_id": commit_id,
                    "repo": repo,
                    "pr_number": pr_number,
                    "reactions": reactions,
                    "positive_reactions_count": _positive_reaction_count(reactions),
                },
                privacy="public",
            ))

        # ── Starred Repositories ───────────────────────────────────────────
        for starred in github_data.starred_repos:
            full_name = starred.get("full_name") or ""
            if not full_name or "/" not in full_name:
                continue
            external_id = f"starred:{full_name}"
            if external_id in since:
                continue
            owner, repo_name = full_name.split("/", 1)
            description = starred.get("description") or ""
            topics = starred.get("topics") or []
            language = starred.get("language") or ""
            content = "\n".join(
                [
                    f"Starred repository: {full_name}",
                    f"Description: {description}",
                    f"Topics: {', '.join(topics) if topics else '<none>'}",
                    f"Language: {language or '<unknown>'}",
                ]
            )

            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="starred",
                content=content,
                context="general",
                evidence_date=_parse_github_date(starred.get("updated_at") or starred.get("pushed_at")),
                source_uri=starred.get("html_url"),
                scope={"owner": owner, "repo": repo_name},
                raw_body=description,
                raw_body_ref=f"github:starred:{full_name}",
                raw_context={
                    "ref": f"github:starred/{full_name}",
                    "topics": topics,
                    "language": language,
                },
                provenance={
                    "collector": "github",
                    "github_api": "users.listStarred",
                    "confidence": 0.95,
                },
                metadata={
                    "owner": owner,
                    "repo": repo_name,
                    "topics": topics,
                    "language": language,
                    "stargazers_count": starred.get("stargazers_count"),
                },
                privacy="public",
            ))

        # ── Watched / Subscribed Repositories ────────────────────────────
        for watched in github_data.watched_repos:
            full_name = watched.get("full_name") or ""
            if not full_name or "/" not in full_name:
                continue
            external_id = f"watched:{full_name}"
            if external_id in since:
                continue
            owner, repo_name = full_name.split("/", 1)
            description = watched.get("description") or ""
            topics = watched.get("topics") or []
            language = watched.get("language") or ""
            content = "\n".join(
                [
                    f"Watched repository: {full_name}",
                    f"Description: {description}",
                    f"Topics: {', '.join(topics) if topics else '<none>'}",
                    f"Language: {language or '<unknown>'}",
                ]
            )

            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="watched",
                content=content,
                context="general",
                evidence_date=_parse_github_date(watched.get("updated_at") or watched.get("pushed_at")),
                source_uri=watched.get("html_url"),
                scope={"owner": owner, "repo": repo_name},
                raw_body=description,
                raw_body_ref=f"github:watched:{full_name}",
                raw_context={
                    "ref": f"github:watched/{full_name}",
                    "topics": topics,
                    "language": language,
                },
                provenance={
                    "collector": "github",
                    "github_api": "users.listWatched",
                    "confidence": 0.95,
                },
                metadata={
                    "owner": owner,
                    "repo": repo_name,
                    "topics": topics,
                    "language": language,
                    "stargazers_count": watched.get("stargazers_count"),
                },
                privacy="public",
            ))

        # ── Commit Comments (event-derived) ──────────────────────────────
        for comment in github_data.commit_comments:
            comment_id = comment.get("id")
            repo = comment.get("repo") or ""
            commit_id = comment.get("commit_id") or ""
            if not comment_id or not repo or not commit_id:
                continue
            external_id = f"commit_comment:{repo}@{commit_id}/{comment_id}"
            if external_id in since:
                continue
            body = comment.get("body") or ""
            author = (comment.get("user") or {}).get("login") or (comment.get("author") or "")
            path = comment.get("path") or ""
            line = comment.get("line")

            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="commit_comment",
                content=body,
                context="code_review",
                evidence_date=_parse_github_date(comment.get("created_at") or comment.get("updated_at")),
                source_uri=comment.get("html_url"),
                author_id=author,
                scope={"type": "repo", "id": repo, "commit": commit_id, "path": path, "line": line},
                raw_body=body,
                raw_body_ref=f"github:commit_comment:{repo}@{commit_id}/{comment_id}",
                raw_context={
                    "ref": f"github:commit_comment/{repo}/{commit_id}/{comment_id}",
                    "path": path,
                    "line": line,
                },
                provenance={
                    "collector": "github",
                    "github_api": "events.commitComment",
                    "confidence": 0.9,
                },
                metadata={
                    "repo": repo,
                    "commit_id": commit_id,
                    "path": path,
                    "line": line,
                },
                privacy="public",
            ))

        # ── Timeline Events (event-derived) ──────────────────────────────
        for event in github_data.timeline_events:
            event_id = event.get("id")
            repo = event.get("repo") or ""
            number = event.get("number")
            if not event_id or not repo or not number:
                continue
            external_id = f"timeline:{repo}#{number}/{event_id}"
            if external_id in since:
                continue
            event_type = event.get("type") or "unknown"
            action = event.get("action") or "unknown"
            actor = event.get("actor") or ""
            content = (
                f"Timeline event in {repo}#{number}\n"
                f"Type: {event_type}\n"
                f"Action: {action}\n"
                f"Actor: {actor}"
            )
            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="timeline_event",
                content=content,
                context="issue_discussion",
                evidence_date=_parse_github_date(event.get("created_at")),
                scope={"type": "repo", "id": repo, "number": number},
                raw_body=content,
                raw_body_ref=f"github:timeline:{repo}#{number}/{event_id}",
                raw_context={
                    "ref": f"github:timeline/{repo}/{number}/{event_id}",
                    "event": event,
                },
                provenance={
                    "collector": "github",
                    "github_api": "users.events",
                    "confidence": 0.85,
                },
                metadata={
                    "repo": repo,
                    "number": number,
                    "event_type": event_type,
                    "action": action,
                    "actor": actor,
                },
                privacy="public",
            ))

        # ── Ingestion stop reasons (run telemetry) ───────────────────────
        for idx, stop in enumerate(github_data.stop_reasons):
            if not isinstance(stop, dict):
                continue
            phase = str(stop.get("phase") or "unknown")
            reason = str(stop.get("stop_reason") or "unknown")
            external_id = f"github_stop:{phase}:{reason}:{idx}"
            if external_id in since:
                continue
            content = json.dumps(stop, sort_keys=True)
            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="ingestion_stop_reason",
                content=content,
                context="metadata",
                metadata=stop,
                raw_body=content,
                raw_body_ref=f"github:stop_reason:{phase}:{reason}:{idx}",
                raw_context={"ref": "github:ingestion/stop_reason", "stop_reason": stop},
                provenance={"collector": "github", "confidence": 1.0},
                privacy="public",
            ))

        # ── Gists ───────────────────────────────────────────────────────────
        for gist in github_data.gists:
            gist_id = gist.get("id") or ""
            if not gist_id:
                continue
            external_id = f"gist:{gist_id}"
            if external_id in since:
                continue
            description = gist.get("description") or ""
            files = gist.get("files_enriched") or []
            parts = [f"Gist: {gist_id}", f"Description: {description or '<none>'}"]
            filenames: list[str] = []
            for file in files:
                if not isinstance(file, dict):
                    continue
                filename = file.get("filename") or "untitled"
                filenames.append(filename)
                content = file.get("content") or ""
                parts.append(f"File: {filename}\n{_truncate(content, 5000)}")

            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="gist",
                content="\n\n".join(parts),
                context="code_change",
                evidence_date=_parse_github_date(gist.get("created_at") or gist.get("updated_at")),
                source_uri=gist.get("html_url"),
                author_id=(gist.get("owner") or {}).get("login"),
                scope={"gist_id": gist_id},
                raw_body=description,
                raw_body_ref=f"github:gist:{gist_id}",
                raw_context={
                    "ref": f"github:gist/{gist_id}",
                    "files": files,
                },
                provenance={
                    "collector": "github",
                    "github_api": "gists.listForUser",
                    "confidence": 0.95,
                },
                metadata={
                    "gist_id": gist_id,
                    "file_count": len(files),
                    "filenames": filenames,
                    "public": gist.get("public"),
                },
                privacy="public" if gist.get("public", True) else "private",
            ))

        # ── Issues (non-PR) ───────────────────────────────────────────────
        for issue in github_data.issues:
            number = issue.get("number")
            repo = _repo_from_pr(issue)
            if not number or not repo:
                continue
            count_for_repo = issue_count_by_repo.get(repo, 0)
            if count_for_repo >= settings.github_max_commits_per_repo:
                continue
            if issue.get("pull_request"):
                continue
            external_id = f"issue:{repo}#{number}"
            if external_id in since:
                continue

            title = issue.get("title") or ""
            body = issue.get("body") or ""
            capped_body = _truncate(body, MAX_PR_BODY_CHARS) if body else ""
            state = issue.get("state") or ""
            author = (issue.get("user") or {}).get("login") or ""
            reactions = _reaction_counts(issue)
            reaction_summary = (
                f"Reactions: {reactions.get('total_count', 0)} total "
                f"(+1={reactions.get('+1', 0)}, heart={reactions.get('heart', 0)}, "
                f"hooray={reactions.get('hooray', 0)}, rocket={reactions.get('rocket', 0)})"
            )

            content_parts = [
                f"Issue #{number}: {title}",
                f"Repository: {repo}",
                f"State: {state}",
                reaction_summary,
            ]
            if capped_body:
                content_parts.append(f"Description:\n{capped_body}")

            date_str = issue.get("created_at") or issue.get("updated_at")
            issue_count_by_repo[repo] = count_for_repo + 1
            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="issue",
                content="\n".join(content_parts),
                context="issue_discussion",
                evidence_date=_parse_github_date(date_str),
                source_uri=issue.get("html_url"),
                author_id=author,
                target_id=f"github:{repo}#{number}",
                scope={"type": "repo", "id": repo, "issue_number": number},
                raw_body=capped_body,
                raw_body_ref=f"github:issue:{repo}#{number}",
                raw_context={
                    "ref": f"github:issue/{repo}/{number}",
                    "state": state,
                    "title": title,
                    "reactions": reactions,
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
                    "reactions": reactions,
                    "positive_reactions_count": _positive_reaction_count(reactions),
                },
                privacy="public",
            ))

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
            capped_body = _truncate(body, MAX_PR_BODY_CHARS) if body else ""
            state = pr.get("state") or ""
            author = pr.get("user", {}).get("login") or ""
            reactions = _reaction_counts(pr)
            content_parts = [
                f"Pull Request #{number}: {title}",
                f"Repository: {repo}",
                f"State: {state}",
            ]
            if reactions:
                content_parts.append(
                    f"Reactions: {reactions.get('total_count', 0)} total "
                    f"(+1={reactions.get('+1', 0)}, heart={reactions.get('heart', 0)})"
                )
            if capped_body:
                content_parts.append(f"Description:\n{capped_body}")

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

            collected_items.append(EvidenceItem(
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
                raw_body=capped_body,
                raw_body_ref=f"github:pull_request:{repo}#{number}" if repo else None,
                raw_context={
                    "ref": f"github:pull_request/{repo}/{number}" if repo else f"github:pull_request/{number}",
                    "state": state,
                    "title": title,
                    "reactions": reactions,
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
                    "reactions": reactions,
                    "positive_reactions_count": _positive_reaction_count(reactions),
                },
                privacy="public",
            ))

        # ── PR Commit SHA Lists ─────────────────────────────────────────────
        for pr_commits in github_data.pr_commits:
            repo = pr_commits.get("repo") or ""
            pr_number = pr_commits.get("pr_number")
            commit_shas = pr_commits.get("commit_shas") or []
            if not repo or not pr_number or not commit_shas:
                continue
            external_id = f"pr_commits:{repo}#{pr_number}"
            if external_id in since:
                continue

            content = "\n".join(
                [
                    f"PR commit list: {repo}#{pr_number}",
                    "Commit SHAs:",
                    *(f"- {sha}" for sha in commit_shas),
                ]
            )

            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="pr_commits",
                content=content,
                context="code_change",
                evidence_date=None,
                source_uri=pr_commits.get("html_url"),
                target_id=f"github:{repo}#{pr_number}",
                scope={"type": "repo", "id": repo, "pr_number": pr_number},
                raw_body="\n".join(commit_shas),
                raw_body_ref=f"github:pull_request_commits:{repo}#{pr_number}",
                raw_context={
                    "ref": f"github:pull_request_commits/{repo}/{pr_number}",
                    "commit_shas": commit_shas,
                    "count": len(commit_shas),
                },
                provenance={
                    "collector": "github",
                    "github_api": "repos.pulls.listCommits",
                    "confidence": 0.95,
                },
                metadata={
                    "repo": repo,
                    "pr_number": pr_number,
                    "commit_shas": commit_shas,
                    "commit_count": len(commit_shas),
                },
                privacy="public",
            ))

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
            thread_diff_hunk = _truncate(thread.get("diff_hunk") or "", MAX_DIFF_HUNK_CHARS)
            thread_reactions = _thread_reactions(comments)

            collected_items.append(EvidenceItem(
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
                    "diff_hunk": thread_diff_hunk,
                    "comment_ids": [c.get("id") for c in comments if c.get("id") is not None],
                    "reactions": thread_reactions,
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
                    "diff_hunk": thread_diff_hunk,
                    "comment_ids": [c.get("id") for c in comments if c.get("id") is not None],
                    "authors": authors,
                    "reactions": thread_reactions,
                    "positive_reactions_count": _positive_reaction_count(thread_reactions),
                },
                privacy="public",
            ))

        # ── PR Review State Events ──────────────────────────────────────────
        for review in github_data.pull_request_reviews:
            review_id = review.get("id")
            repo = review.get("repo") or _repo_from_review_event(review)
            pr_number = review.get("pr_number") or _pr_number_from_review_event(review)
            if not review_id or not repo or not pr_number:
                continue
            external_id = f"pr_review:{repo}#{pr_number}:{review_id}"
            if external_id in since:
                continue

            body = review.get("body") or ""
            author = (review.get("user") or {}).get("login") or ""
            state = review.get("state") or ""
            submitted_at = review.get("submitted_at") or review.get("created_at")
            reactions = _reaction_counts(review)

            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="pr_review",
                content=_format_pr_review_event(review),
                context="code_review",
                evidence_date=_parse_github_date(submitted_at),
                source_uri=review.get("html_url") or review.get("pr_html_url"),
                author_id=author,
                target_id=f"github:{repo}#{pr_number}",
                scope={"type": "repo", "id": repo, "pr_number": pr_number},
                raw_body=body,
                raw_body_ref=f"github:pull_request_review:{review_id}",
                raw_context={
                    "ref": f"github:pull_request_review/{repo}/{pr_number}/{review_id}",
                    "pr_node_id": review.get("pr_node_id"),
                    "commit_id": review.get("commit_id"),
                    "state": state,
                    "submitted_at": submitted_at,
                    "pull_request_url": review.get("pull_request_url"),
                    "pr_html_url": review.get("pr_html_url"),
                    "reactions": reactions,
                },
                provenance={
                    "collector": "github",
                    "github_api": "repos.pulls.listReviews",
                    "review_state_event": True,
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.95 if author else 0.75,
                },
                metadata={
                    "review_id": review_id,
                    "repo": repo,
                    "pr_number": pr_number,
                    "author": author,
                    "state": state,
                    "commit_id": review.get("commit_id"),
                    "submitted_at": submitted_at,
                    "pr_node_id": review.get("pr_node_id"),
                    "html_url": review.get("html_url"),
                    "reactions": reactions,
                    "positive_reactions_count": _positive_reaction_count(reactions),
                },
                privacy="public",
            ))

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
            diff_hunk = _truncate(review.get("diff_hunk") or "", MAX_DIFF_HUNK_CHARS)
            author = review.get("user", {}).get("login") or ""
            repo = _repo_from_review_comment(review)
            pr_number = _pr_number_from_review_comment(review)
            line = review.get("line") or review.get("original_line")
            side = review.get("side")
            reactions = _reaction_counts(review)
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

            collected_items.append(EvidenceItem(
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
                    "reactions": reactions,
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
                    "file_path": path,
                    "diff_hunk": diff_hunk,
                    "author": author,
                    "line": review.get("line"),
                    "original_line": review.get("original_line"),
                    "start_line": review.get("start_line"),
                    "side": side,
                    "in_reply_to_id": review.get("in_reply_to_id"),
                    "pull_request_review_id": review.get("pull_request_review_id"),
                    "html_url": review.get("html_url"),
                    "reactions": reactions,
                    "positive_reactions_count": _positive_reaction_count(reactions),
                },
                privacy="public",
            ))

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
            reactions = _reaction_counts(comment)
            content_parts = [f"Issue comment (id={comment_id})"]
            if issue_url:
                content_parts.append(f"Issue: {issue_url}")
            if author:
                content_parts.append(f"Author: {author}")
            if body:
                content_parts.append(f"Comment:\n{body[:1000]}")

            date_str = comment.get("created_at") or comment.get("updated_at")
            evidence_date = _parse_github_date(date_str)

            collected_items.append(EvidenceItem(
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
                    "reactions": reactions,
                },
                provenance={
                    "collector": "github",
                    "authored_by_subject": bool(
                        identifier and author and author.casefold() == identifier.casefold()
                    ),
                    "confidence": 0.95 if author else 0.75,
                },
                metadata={
                    "comment_id": comment_id,
                    "author": author,
                    "repo": repo,
                    "issue_number": issue_number,
                    "reactions": reactions,
                    "positive_reactions_count": _positive_reaction_count(reactions),
                },
                privacy="public",
            ))

        # ── Issue / PR Discussion Threads ───────────────────────────────────
        for thread in github_data.issue_threads:
            repo = thread.get("repo") or ""
            number = thread.get("issue_number") or thread.get("pr_number")
            if not repo or not number:
                continue
            comments = thread.get("comments") or []
            latest_comment_id = _latest_comment_id(comments)
            external_id = f"issue_thread:{repo}#{number}@{latest_comment_id}"
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
            thread_reactions = _thread_reactions(comments)

            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="issue_thread",
                content=_format_issue_thread(thread),
                context="issue_discussion",
                evidence_date=_parse_github_date(date_str),
                source_uri=thread.get("html_url") or first_comment.get("html_url"),
                author_id=(first_comment.get("user") or {}).get("login"),
                target_id=f"github:{repo}#{number}",
                scope={
                    "type": "repo",
                    "id": repo,
                    "issue_number": number,
                    "is_pull_request": bool(thread.get("pr_number")),
                },
                raw_body=_thread_raw_body(comments),
                raw_body_ref=f"github:issue_thread:{repo}#{number}@{latest_comment_id}",
                raw_context={
                    "ref": f"github:issue_thread/{repo}/{number}",
                    "pr_node_id": thread.get("pr_node_id"),
                    "issue_node_id": thread.get("issue_node_id"),
                    "comment_ids": [c.get("id") for c in comments if c.get("id") is not None],
                    "reactions": thread_reactions,
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
                    "pr_number": thread.get("pr_number"),
                    "issue_number": thread.get("issue_number") or number,
                    "is_pull_request": bool(thread.get("pr_number")),
                    "pr_node_id": thread.get("pr_node_id"),
                    "issue_node_id": thread.get("issue_node_id"),
                    "html_url": thread.get("html_url"),
                    "comment_ids": [c.get("id") for c in comments if c.get("id") is not None],
                    "authors": authors,
                    "reactions": thread_reactions,
                    "positive_reactions_count": _positive_reaction_count(thread_reactions),
                },
                privacy="public",
            ))

        # ── Discussion Primitive Surfaces ───────────────────────────────────
        for thread in github_data.issue_threads:
            repo = thread.get("repo") or ""
            number = thread.get("issue_number") or thread.get("pr_number")
            if not repo or not number:
                continue
            comments = thread.get("comments") or []
            latest_comment_id = _latest_comment_id(comments)
            external_id = f"discussion:issue:{repo}#{number}@{latest_comment_id}"
            if external_id in since:
                continue
            comment_count = len(comments)
            authors = _comment_authors(comments)
            thread_reactions = _thread_reactions(comments)
            date_str = (comments[0] if comments else {}).get("created_at")
            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="discussion",
                content=_format_issue_thread(thread),
                context="issue_discussion",
                evidence_date=_parse_github_date(date_str),
                source_uri=thread.get("html_url") or (comments[0] if comments else {}).get("html_url"),
                author_id=(comments[0] if comments else {}).get("user", {}).get("login"),
                target_id=f"github:{repo}#{number}",
                scope={
                    "type": "repo",
                    "id": repo,
                    "issue_number": number,
                    "discussion_kind": "issue_thread",
                    "is_pull_request": bool(thread.get("pr_number")),
                },
                raw_body=_thread_raw_body(comments),
                raw_body_ref=f"github:discussion:issue:{repo}#{number}@{latest_comment_id}",
                raw_context={
                    "ref": f"github:discussion/issue_thread/{repo}/{number}",
                    "thread": thread,
                    "reactions": thread_reactions,
                },
                provenance={
                    "collector": "github",
                    "primitive": "discussion",
                    "discussion_kind": "issue_thread",
                    "thread_snapshot": True,
                    "confidence": 0.95 if comments else 0.7,
                },
                metadata={
                    "repo": repo,
                    "issue_number": thread.get("issue_number") or number,
                    "pr_number": thread.get("pr_number"),
                    "is_pull_request": bool(thread.get("pr_number")),
                    "discussion_kind": "issue_thread",
                    "comment_count": comment_count,
                    "participants": authors,
                    "reactions": thread_reactions,
                    "positive_reactions_count": _positive_reaction_count(thread_reactions),
                },
                privacy="public",
            ))

        for thread in github_data.pr_review_threads:
            thread_id = thread.get("thread_id")
            repo = thread.get("repo") or ""
            pr_number = thread.get("pr_number")
            if not thread_id or not repo or not pr_number:
                continue
            comments = thread.get("comments") or []
            latest_comment_id = _latest_comment_id(comments)
            external_id = f"discussion:pr_review:{thread_id}@{latest_comment_id}"
            if external_id in since:
                continue
            comment_count = len(comments)
            authors = _comment_authors(comments)
            thread_reactions = _thread_reactions(comments)
            date_str = (comments[0] if comments else {}).get("created_at")
            path = thread.get("path") or ""
            line = thread.get("line") or thread.get("original_line")
            collected_items.append(EvidenceItem(
                external_id=external_id,
                source_type=self.name,
                item_type="discussion",
                content=_format_pr_review_thread(thread),
                context="code_review",
                evidence_date=_parse_github_date(date_str),
                source_uri=(comments[0] if comments else {}).get("html_url"),
                author_id=(comments[0] if comments else {}).get("user", {}).get("login"),
                target_id=_review_target_id(repo, pr_number, path, line),
                scope=_review_scope(repo, pr_number, path, line, thread.get("side")),
                raw_body=_thread_raw_body(comments),
                raw_body_ref=f"github:discussion:pr_review:{thread_id}@{latest_comment_id}",
                raw_context={
                    "ref": f"github:discussion/pr_review_thread/{thread_id}",
                    "thread": thread,
                    "reactions": thread_reactions,
                },
                provenance={
                    "collector": "github",
                    "primitive": "discussion",
                    "discussion_kind": "pr_review_thread",
                    "thread_snapshot": True,
                    "confidence": 0.95 if comments else 0.7,
                },
                metadata={
                    "repo": repo,
                    "pr_number": pr_number,
                    "thread_id": thread_id,
                    "path": path,
                    "line": line,
                    "discussion_kind": "pr_review_thread",
                    "comment_count": comment_count,
                    "participants": authors,
                    "reactions": thread_reactions,
                    "positive_reactions_count": _positive_reaction_count(thread_reactions),
                },
                privacy="public",
            ))

        selected_external_ids = _sample_by_recency_windows(collected_items)
        selected_external_ids = _enforce_repo_minimums(
            collected_items,
            selected_external_ids,
            repo_activity,
        )

        for item in collected_items:
            if item.external_id == "language_diversity_summary:github":
                yield _apply_access_controls(
                    item,
                    identifier=identifier,
                    repo_visibility_index=repo_visibility_index,
                )
                continue
            if item.external_id not in selected_external_ids:
                continue

            metadata = dict(item.metadata or {})
            repo_name = _repo_for_item(item)
            if repo_name and not _repo_allowed_by_org_policy(repo_name, identifier):
                continue
            metadata["sampling_window"] = classify_recency_window(item.evidence_date)
            if repo_name and repo_name in repo_activity:
                stats = repo_activity[repo_name]
                metadata["repo_activity"] = {
                    "estimated_loc": int(stats.get("estimated_loc") or 0),
                    "commit_count": int(stats.get("commit_count") or 0),
                    "pr_count": int(stats.get("pr_count") or 0),
                    "non_trivial": bool(stats.get("non_trivial")),
                }
                metadata["repo_languages"] = github_data.repo_languages.get(repo_name, {})
            item.metadata = metadata
            yield _apply_access_controls(
                item,
                identifier=identifier,
                repo_visibility_index=repo_visibility_index,
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


def _reaction_counts(item: dict[str, Any]) -> dict[str, int]:
    reactions = item.get("reactions")
    if not isinstance(reactions, dict):
        return {}
    counts: dict[str, int] = {}
    for key in ("total_count", "+1", "-1", "laugh", "hooray", "confused", "heart", "rocket", "eyes"):
        value = reactions.get(key)
        if isinstance(value, int):
            counts[key] = value
    return counts


def _positive_reaction_count(reactions: dict[str, int]) -> int:
    return int(reactions.get("+1", 0)) + int(reactions.get("heart", 0)) + int(
        reactions.get("hooray", 0)
    ) + int(reactions.get("rocket", 0))


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


def _thread_reactions(comments: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for comment in comments:
        reactions = _reaction_counts(comment)
        for key, value in reactions.items():
            totals[key] = totals.get(key, 0) + int(value)
    return totals


def _repo_for_item(item: EvidenceItem) -> str:
    if item.metadata and isinstance(item.metadata.get("repo"), str):
        return item.metadata.get("repo") or ""
    if item.scope and isinstance(item.scope.get("id"), str):
        return item.scope.get("id") or ""
    return ""


def _keep_by_ratio(key: str, ratio: float) -> bool:
    if ratio >= 1.0:
        return True
    if ratio <= 0.0:
        return False
    digest = sha1(key.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return bucket < ratio


def _sample_by_recency_windows(items: list[EvidenceItem]) -> set[str]:
    selected: set[str] = set()
    for item in items:
        window = classify_recency_window(item.evidence_date)
        if window == "recent":
            selected.add(item.external_id)
            continue
        if window == "mid" and _keep_by_ratio(item.external_id, MID_WINDOW_KEEP_RATIO):
            selected.add(item.external_id)
            continue
        if window == "historical" and _keep_by_ratio(item.external_id, HISTORICAL_WINDOW_KEEP_RATIO):
            selected.add(item.external_id)
    return selected


def _enforce_repo_minimums(
    items: list[EvidenceItem],
    selected_external_ids: set[str],
    repo_activity: dict[str, dict[str, Any]],
) -> set[str]:
    for repo_name, stats in repo_activity.items():
        if not stats.get("non_trivial"):
            continue
        repo_items = [
            item
            for item in items
            if _repo_for_item(item) == repo_name and item.item_type in REPO_SCOPED_ITEM_TYPES
        ]
        if not repo_items:
            continue
        target_count = min(MIN_EVIDENCE_PER_NON_TRIVIAL_REPO, len(repo_items))
        current_count = sum(1 for item in repo_items if item.external_id in selected_external_ids)
        if current_count >= target_count:
            continue

        candidates = [item for item in repo_items if item.external_id not in selected_external_ids]
        candidates.sort(
            key=lambda item: (
                classify_recency_window(item.evidence_date) != "recent",
                item.evidence_date or datetime.min.replace(tzinfo=timezone.utc),
                item.external_id,
            ),
            reverse=True,
        )
        for candidate in candidates:
            selected_external_ids.add(candidate.external_id)
            current_count += 1
            if current_count >= target_count:
                break
    return selected_external_ids


def _build_language_diversity_item(github_data: GitHubData) -> EvidenceItem | None:
    language_totals = _aggregate_languages(github_data)
    if not language_totals:
        return None

    repos_with_languages = sum(1 for v in github_data.repo_languages.values() if v)
    distinct_languages = len(language_totals)
    summary = (
        f"Language diversity summary: {distinct_languages} distinct languages "
        f"across {repos_with_languages} repos."
    )
    metadata = {
        "distinct_languages": distinct_languages,
        "repos_with_languages": repos_with_languages,
        "language_totals": language_totals,
    }
    return EvidenceItem(
        external_id="language_diversity_summary:github",
        source_type="github",
        item_type="language_diversity_summary",
        content=summary,
        context="general",
        metadata=metadata,
        raw_context={"ref": "github:language_diversity_summary"},
        provenance={
            "collector": "github",
            "confidence": 0.95,
        },
        privacy="public",
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
    number = thread.get("issue_number") or thread.get("pr_number")
    comments = thread.get("comments") or []

    parts = [f"Issue/PR discussion thread: {repo}#{number}"]
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


def _format_pr_review_event(review: dict[str, Any]) -> str:
    repo = review.get("repo") or _repo_from_review_event(review)
    pr_number = review.get("pr_number") or _pr_number_from_review_event(review)
    state = review.get("state") or "UNKNOWN"
    author = (review.get("user") or {}).get("login") or "unknown"
    submitted_at = review.get("submitted_at") or review.get("created_at") or ""
    body = review.get("body") or ""

    parts = [f"PR review state: {repo}#{pr_number}", f"State: {state}"]
    if author:
        parts.append(f"Reviewer: {author}")
    if submitted_at:
        parts.append(f"Submitted: {submitted_at}")
    if review.get("commit_id"):
        parts.append(f"Commit: {review['commit_id']}")
    if body:
        parts.append(f"Review body:\n{_truncate(body, 1600)}")
    else:
        parts.append("Review body: <empty>")
    return "\n".join(parts)


def _repo_from_review_event(review: dict[str, Any]) -> str:
    pull_request_url = review.get("pull_request_url") or ""
    if "/repos/" not in pull_request_url:
        return ""
    repo_and_tail = pull_request_url.rsplit("/repos/", 1)[1]
    parts = repo_and_tail.split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return ""


def _pr_number_from_review_event(review: dict[str, Any]) -> int | None:
    pull_request_url = review.get("pull_request_url") or ""
    try:
        return int(pull_request_url.rstrip("/").rsplit("/", 1)[-1])
    except (TypeError, ValueError):
        return None


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
