"""GitHub migration archive ingestion source.

This source is intended for operator-invoked local archive bootstrap imports.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from app.ingestion.github_archive import (
    ArchiveMetadata,
    ArchiveRecord,
    load_github_migration_archive,
)
from app.plugins.base import EvidenceItem, IngestionSource


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        return datetime.fromisoformat(normalized).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _repo_full_name(payload: dict[str, Any]) -> str:
    repo = payload.get("repo")
    if isinstance(repo, str) and repo.strip():
        return repo.strip()
    if isinstance(repo, dict):
        full_name = repo.get("full_name")
        if isinstance(full_name, str) and full_name.strip():
            return full_name.strip()

    for key in ("repository", "base"):
        value = payload.get(key)
        if isinstance(value, dict):
            repo_value = value.get("repo")
            if isinstance(repo_value, dict):
                full_name = repo_value.get("full_name")
                if isinstance(full_name, str) and full_name.strip():
                    return full_name.strip()
            full_name = value.get("full_name")
            if isinstance(full_name, str) and full_name.strip():
                return full_name.strip()

    repo_name = payload.get("repository_name")
    if isinstance(repo_name, str) and repo_name.strip():
        return repo_name.strip()
    return ""


def _extract_number(payload: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _first_non_empty_str(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _author_login(payload: dict[str, Any]) -> str:
    user = payload.get("user")
    if isinstance(user, dict):
        login = user.get("login")
        if isinstance(login, str) and login.strip():
            return login.strip()
    return _first_non_empty_str(payload, "author", "actor")


def _review_scope(repo: str, number: int | None, path: str | None = None) -> dict[str, Any] | None:
    if not repo:
        return None
    scope: dict[str, Any] = {"type": "repo", "id": repo}
    if number is not None:
        scope["pr_number"] = number
    if path:
        scope["path"] = path
    return scope


def _provenance(
    metadata: ArchiveMetadata,
    *,
    family: str,
    member_path: str,
) -> dict[str, Any]:
    return {
        "collector": "github_archive",
        "archive_hash": metadata.archive_hash,
        "archive_path": metadata.archive_path,
        "snapshot_timestamp": (
            metadata.snapshot_timestamp.isoformat() if metadata.snapshot_timestamp else None
        ),
        "migration_id": metadata.migration_id,
        "migration_metadata": metadata.migration_metadata,
        "archive_family": family,
        "archive_member": member_path,
        "confidence": 0.95,
    }


def _pr_item(record: ArchiveRecord, metadata: ArchiveMetadata) -> EvidenceItem | None:
    payload = record.payload
    repo = _repo_full_name(payload)
    number = _extract_number(payload, "number", "pull_request_number")
    if not repo or number is None:
        return None

    title = _first_non_empty_str(payload, "title")
    body = _first_non_empty_str(payload, "body")
    state = _first_non_empty_str(payload, "state")
    author = _author_login(payload)
    created_at = _parse_datetime(_first_non_empty_str(payload, "created_at", "updated_at"))

    content_parts = [f"Pull Request #{number}: {title or '<untitled>'}", f"Repository: {repo}"]
    if state:
        content_parts.append(f"State: {state}")
    if body:
        content_parts.append(f"Description:\n{body[:8000]}")

    return EvidenceItem(
        external_id=f"archive_pr:{repo}#{number}",
        source_type="github_archive",
        item_type="pr",
        content="\n".join(content_parts),
        context="issue_discussion",
        evidence_date=created_at,
        source_uri=_first_non_empty_str(payload, "html_url", "url"),
        author_id=author or None,
        target_id=f"github:{repo}#{number}",
        scope={"type": "repo", "id": repo, "pr_number": number},
        raw_body=body or None,
        raw_body_ref=f"github_archive:pull_requests:{repo}#{number}",
        raw_context={
            "ref": f"github_archive/pull_requests/{repo}/{number}",
            "archive_member": record.member_path,
            "raw": payload,
        },
        provenance=_provenance(metadata, family=record.family, member_path=record.member_path),
        metadata={
            "archive_family": record.family,
            "repo": repo,
            "number": number,
            "state": state or None,
        },
        privacy="public",
    )


def _pr_review_item(record: ArchiveRecord, metadata: ArchiveMetadata) -> EvidenceItem | None:
    payload = record.payload
    repo = _repo_full_name(payload)
    number = _extract_number(payload, "pull_request_number", "pr_number", "number")
    review_id = payload.get("id")
    if not repo or number is None or review_id is None:
        return None

    state = _first_non_empty_str(payload, "state")
    body = _first_non_empty_str(payload, "body")
    author = _author_login(payload)
    submitted_at = _parse_datetime(
        _first_non_empty_str(payload, "submitted_at", "created_at", "updated_at")
    )

    content = (
        f"PR review state: {repo}#{number}\n"
        f"State: {state or 'UNKNOWN'}\n"
        f"Reviewer: {author or 'unknown'}\n"
        f"Review body:\n{body if body else '<empty>'}"
    )

    return EvidenceItem(
        external_id=f"archive_pr_review:{repo}#{number}:{review_id}",
        source_type="github_archive",
        item_type="pr_review",
        content=content,
        context="code_review",
        evidence_date=submitted_at,
        source_uri=_first_non_empty_str(payload, "html_url", "url"),
        author_id=author or None,
        target_id=f"github:{repo}#{number}",
        scope=_review_scope(repo, number),
        raw_body=body or None,
        raw_body_ref=f"github_archive:pull_request_reviews:{review_id}",
        raw_context={
            "ref": f"github_archive/pull_request_reviews/{repo}/{number}/{review_id}",
            "archive_member": record.member_path,
            "raw": payload,
        },
        provenance=_provenance(metadata, family=record.family, member_path=record.member_path),
        metadata={
            "archive_family": record.family,
            "repo": repo,
            "pr_number": number,
            "review_id": review_id,
            "state": state or None,
        },
        privacy="public",
    )


def _review_comment_item(record: ArchiveRecord, metadata: ArchiveMetadata) -> EvidenceItem | None:
    payload = record.payload
    comment_id = payload.get("id")
    if comment_id is None:
        return None

    repo = _repo_full_name(payload)
    number = _extract_number(payload, "pull_request_number", "pr_number", "number")
    path = _first_non_empty_str(payload, "path")
    body = _first_non_empty_str(payload, "body")
    author = _author_login(payload)
    created_at = _parse_datetime(_first_non_empty_str(payload, "created_at", "updated_at"))

    parts = [f"Review comment (id={comment_id})"]
    if repo:
        parts.append(f"Repository: {repo}")
    if number is not None:
        parts.append(f"Pull Request: #{number}")
    if path:
        parts.append(f"File: {path}")
    if body:
        parts.append(f"Comment:\n{body[:1200]}")

    return EvidenceItem(
        external_id=f"archive_review_comment:{comment_id}",
        source_type="github_archive",
        item_type="review",
        content="\n".join(parts),
        context="code_review",
        evidence_date=created_at,
        source_uri=_first_non_empty_str(payload, "html_url", "url"),
        author_id=author or None,
        target_id=f"github:{repo}#{number}" if repo and number is not None else None,
        scope=_review_scope(repo, number, path),
        raw_body=body or None,
        raw_body_ref=f"github_archive:review_comments:{comment_id}",
        raw_context={
            "ref": f"github_archive/review_comments/{comment_id}",
            "archive_member": record.member_path,
            "raw": payload,
        },
        provenance=_provenance(metadata, family=record.family, member_path=record.member_path),
        metadata={
            "archive_family": record.family,
            "repo": repo,
            "pr_number": number,
            "comment_id": comment_id,
            "path": path or None,
        },
        privacy="public",
    )


def _issue_comment_item(record: ArchiveRecord, metadata: ArchiveMetadata) -> EvidenceItem | None:
    payload = record.payload
    comment_id = payload.get("id")
    if comment_id is None:
        return None

    body = _first_non_empty_str(payload, "body")
    author = _author_login(payload)
    repo = _repo_full_name(payload)
    issue_number = _extract_number(payload, "issue_number", "number")
    created_at = _parse_datetime(_first_non_empty_str(payload, "created_at", "updated_at"))

    return EvidenceItem(
        external_id=f"archive_issue_comment:{comment_id}",
        source_type="github_archive",
        item_type="issue_comment",
        content=body,
        context="issue_discussion",
        evidence_date=created_at,
        source_uri=_first_non_empty_str(payload, "html_url", "url"),
        author_id=author or None,
        target_id=f"github:{repo}#{issue_number}" if repo and issue_number is not None else None,
        scope={"type": "repo", "id": repo, "issue_number": issue_number}
        if repo and issue_number is not None
        else None,
        raw_body=body,
        raw_body_ref=f"github_archive:issue_comments:{comment_id}",
        raw_context={
            "ref": f"github_archive/issue_comments/{comment_id}",
            "archive_member": record.member_path,
            "raw": payload,
        },
        provenance=_provenance(metadata, family=record.family, member_path=record.member_path),
        metadata={
            "archive_family": record.family,
            "repo": repo,
            "issue_number": issue_number,
            "comment_id": comment_id,
        },
        privacy="public",
    )


def _issue_event_item(record: ArchiveRecord, metadata: ArchiveMetadata) -> EvidenceItem | None:
    payload = record.payload
    event_id = payload.get("id")
    if event_id is None:
        return None

    repo = _repo_full_name(payload)
    number = _extract_number(payload, "issue_number", "number")
    event_type = _first_non_empty_str(payload, "event", "type") or "unknown"
    actor = _author_login(payload)
    created_at = _parse_datetime(_first_non_empty_str(payload, "created_at", "updated_at"))
    content = (
        f"Issue event\n"
        f"Repository: {repo or '<unknown>'}\n"
        f"Issue: #{number if number is not None else '?'}\n"
        f"Event: {event_type}\n"
        f"Actor: {actor or 'unknown'}"
    )

    return EvidenceItem(
        external_id=f"archive_issue_event:{event_id}",
        source_type="github_archive",
        item_type="issue_event",
        content=content,
        context="issue_discussion",
        evidence_date=created_at,
        source_uri=_first_non_empty_str(payload, "html_url", "url"),
        author_id=actor or None,
        scope={"type": "repo", "id": repo, "issue_number": number} if repo else None,
        raw_body=content,
        raw_body_ref=f"github_archive:issue_events:{event_id}",
        raw_context={
            "ref": f"github_archive/issue_events/{event_id}",
            "archive_member": record.member_path,
            "raw": payload,
        },
        provenance=_provenance(metadata, family=record.family, member_path=record.member_path),
        metadata={
            "archive_family": record.family,
            "repo": repo,
            "issue_number": number,
            "event_id": event_id,
            "event_type": event_type,
        },
        privacy="public",
    )


def _commit_comment_item(record: ArchiveRecord, metadata: ArchiveMetadata) -> EvidenceItem | None:
    payload = record.payload
    comment_id = payload.get("id")
    if comment_id is None:
        return None

    repo = _repo_full_name(payload)
    commit_id = _first_non_empty_str(payload, "commit_id", "sha")
    body = _first_non_empty_str(payload, "body")
    author = _author_login(payload)
    created_at = _parse_datetime(_first_non_empty_str(payload, "created_at", "updated_at"))

    if not repo or not commit_id:
        return None

    return EvidenceItem(
        external_id=f"archive_commit_comment:{repo}@{commit_id}/{comment_id}",
        source_type="github_archive",
        item_type="commit_comment",
        content=body,
        context="code_review",
        evidence_date=created_at,
        source_uri=_first_non_empty_str(payload, "html_url", "url"),
        author_id=author or None,
        scope={"type": "repo", "id": repo, "commit": commit_id},
        raw_body=body,
        raw_body_ref=f"github_archive:commit_comments:{comment_id}",
        raw_context={
            "ref": f"github_archive/commit_comments/{repo}/{commit_id}/{comment_id}",
            "archive_member": record.member_path,
            "raw": payload,
        },
        provenance=_provenance(metadata, family=record.family, member_path=record.member_path),
        metadata={
            "archive_family": record.family,
            "repo": repo,
            "commit_id": commit_id,
            "comment_id": comment_id,
        },
        privacy="public",
    )


_FAMILY_NORMALIZERS = {
    "pull_requests": _pr_item,
    "pull_request_reviews": _pr_review_item,
    "review_comments": _review_comment_item,
    "issue_comments": _issue_comment_item,
    "issue_events": _issue_event_item,
    "commit_comments": _commit_comment_item,
}


class GitHubArchiveSource(IngestionSource):
    """Ingest local GitHub migration archives (manual bootstrap path)."""

    name = "github_archive"

    def __init__(self, archive_path: str | None = None) -> None:
        self._archive_path = archive_path

    async def fetch_items(
        self,
        identifier: str,
        mini_id: str,
        session: Any,
        *,
        since_external_ids: set[str] | None = None,
    ) -> AsyncIterator[EvidenceItem]:
        """Yield normalized EvidenceItems for supported archive object families.

        ``identifier`` is treated as the subject username when ``archive_path``
        was configured on the source instance, otherwise as the archive path.
        """
        del mini_id, session  # Source parsing is filesystem-only for phase 1.

        archive_path = self._archive_path or identifier
        loaded = load_github_migration_archive(archive_path)
        seen = since_external_ids or set()

        for record in loaded.records:
            normalizer = _FAMILY_NORMALIZERS.get(record.family)
            if normalizer is None:
                continue
            item = normalizer(record, loaded.metadata)
            if item is None:
                continue
            if item.external_id in seen:
                continue
            yield item
