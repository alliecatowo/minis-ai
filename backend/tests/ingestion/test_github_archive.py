from __future__ import annotations

import io
import json
import tarfile

import pytest

from app.ingestion.github_archive import load_github_migration_archive, summarize_archive_records
from app.plugins.sources.github_archive import GitHubArchiveSource
from scripts.ingest_github_archive import summarize_evidence_items


@pytest.fixture
def github_archive_path(tmp_path):
    archive_path = tmp_path / "github-migration.tar.gz"

    members = {
        "metadata.json": {
            "migration_id": "mig-123",
            "snapshot_timestamp": "2026-04-20T10:00:00Z",
            "requested_by": "mini-owner",
        },
        "pull_requests.json": [
            {
                "id": 1,
                "number": 42,
                "title": "Improve pipeline reliability",
                "body": "Adds retries and telemetry.",
                "state": "closed",
                "repo": "acme/app",
                "html_url": "https://github.com/acme/app/pull/42",
                "user": {"login": "mini"},
                "created_at": "2026-04-01T10:00:00Z",
            }
        ],
        "pull_request_reviews.json": [
            {
                "id": 101,
                "pull_request_number": 42,
                "state": "APPROVED",
                "body": "Looks good.",
                "repo": "acme/app",
                "user": {"login": "mini"},
                "submitted_at": "2026-04-01T11:00:00Z",
            }
        ],
        "review_comments.json": [
            {
                "id": 201,
                "pull_request_number": 42,
                "repo": "acme/app",
                "path": "backend/app/main.py",
                "body": "Please add a regression test.",
                "user": {"login": "mini"},
                "created_at": "2026-04-01T11:30:00Z",
            }
        ],
        "issue_comments.json": [
            {
                "id": 301,
                "issue_number": 7,
                "repo": "acme/app",
                "body": "Can reproduce this locally.",
                "user": {"login": "mini"},
                "created_at": "2026-04-02T09:00:00Z",
            }
        ],
        "issue_events.json": [
            {
                "id": 401,
                "issue_number": 7,
                "repo": "acme/app",
                "event": "closed",
                "actor": "mini",
                "created_at": "2026-04-02T10:00:00Z",
            }
        ],
        "commit_comments.json": [
            {
                "id": 501,
                "repo": "acme/app",
                "commit_id": "deadbeef",
                "body": "This commit needs additional context.",
                "user": {"login": "mini"},
                "created_at": "2026-04-03T09:00:00Z",
            }
        ],
    }

    with tarfile.open(archive_path, "w:gz") as tar:
        for name, payload in members.items():
            raw = json.dumps(payload).encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))

    return archive_path


def test_load_github_migration_archive_extracts_supported_families(github_archive_path):
    loaded = load_github_migration_archive(github_archive_path)

    assert loaded.metadata.archive_hash
    assert loaded.metadata.migration_id == "mig-123"
    assert loaded.metadata.snapshot_timestamp is not None

    summary = summarize_archive_records(loaded.records)
    assert summary["total_records"] == 6
    assert set(summary["included_families"]) == {
        "pull_requests",
        "pull_request_reviews",
        "review_comments",
        "issue_comments",
        "issue_events",
        "commit_comments",
    }


@pytest.mark.asyncio
async def test_github_archive_source_normalizes_required_item_families(github_archive_path):
    source = GitHubArchiveSource(archive_path=str(github_archive_path))

    items = []
    async for item in source.fetch_items(
        identifier="mini",
        mini_id="mini-id",
        session=None,
        since_external_ids={"archive_issue_comment:301"},
    ):
        items.append(item)

    item_types = {item.item_type for item in items}
    assert item_types == {"pr", "pr_review", "review", "issue_event", "commit_comment"}

    for item in items:
        assert item.source_type == "github_archive"
        assert item.provenance is not None
        assert item.provenance["archive_hash"]
        assert item.provenance["migration_id"] == "mig-123"
        assert item.provenance["snapshot_timestamp"] == "2026-04-20T10:00:00+00:00"


@pytest.mark.asyncio
async def test_dry_run_summary_reports_counts(github_archive_path):
    source = GitHubArchiveSource(archive_path=str(github_archive_path))

    items = []
    async for item in source.fetch_items(
        identifier="mini",
        mini_id="mini-id",
        session=None,
        since_external_ids=None,
    ):
        items.append(item)

    summary = summarize_evidence_items(items)
    assert summary["total_items"] == 6
    assert summary["by_item_type"]["pr"] == 1
    assert summary["by_item_type"]["pr_review"] == 1
    assert summary["by_archive_family"]["pull_requests"] == 1
    assert summary["archive_hash"]
    assert summary["migration_id"] == "mig-123"
