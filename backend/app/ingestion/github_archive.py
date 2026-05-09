"""GitHub migration archive helpers.

Phase 1 scope:
- Load local ``.tar.gz`` migration export archives.
- Extract supported JSON object families.
- Produce deterministic archive provenance metadata.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_FAMILIES: tuple[str, ...] = (
    "pull_requests",
    "pull_request_reviews",
    "review_comments",
    "issue_comments",
    "issue_events",
    "commit_comments",
)

_FAMILY_ALIASES = {
    "pull_requests": "pull_requests",
    "pull_request": "pull_requests",
    "pull_request_reviews": "pull_request_reviews",
    "reviews": "pull_request_reviews",
    "review_comments": "review_comments",
    "pull_request_review_comments": "review_comments",
    "issue_comments": "issue_comments",
    "issue_events": "issue_events",
    "timeline_events": "issue_events",
    "commit_comments": "commit_comments",
}

_METADATA_FILENAMES = {
    "metadata",
    "migration",
    "migration_metadata",
    "archive_metadata",
}


@dataclass(slots=True)
class ArchiveRecord:
    family: str
    member_path: str
    payload: dict[str, Any]


@dataclass(slots=True)
class ArchiveMetadata:
    archive_path: str
    archive_hash: str
    snapshot_timestamp: datetime | None
    migration_id: str | None
    migration_metadata: dict[str, Any]


@dataclass(slots=True)
class LoadedGitHubArchive:
    metadata: ArchiveMetadata
    records: list[ArchiveRecord]


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        return datetime.fromisoformat(normalized).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _canonical_family_for_member(member_path: str) -> str | None:
    stem = Path(member_path).stem.lower().replace("-", "_")
    return _FAMILY_ALIASES.get(stem)


def _iter_objects(payload: Any, family: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    if family in payload and isinstance(payload[family], list):
        return [item for item in payload[family] if isinstance(item, dict)]

    for key in ("items", "data", "nodes"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    if any(k in payload for k in ("id", "number", "body", "event")):
        return [payload]
    return []


def _read_json_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> Any:
    file_obj = archive.extractfile(member)
    if file_obj is None:
        return None
    raw = file_obj.read()
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")

    if member.name.endswith((".jsonl", ".ndjson")):
        rows: list[dict[str, Any]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_migration_metadata(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    for candidate in candidates:
        if candidate:
            return candidate
    return {}


def _derive_snapshot_timestamp(metadata: dict[str, Any]) -> datetime | None:
    keys = ("snapshot_timestamp", "snapshot_at", "exported_at", "created_at", "generated_at")
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str):
            parsed = _parse_datetime(value)
            if parsed is not None:
                return parsed

    migration = metadata.get("migration")
    if isinstance(migration, dict):
        for key in keys:
            value = migration.get(key)
            if isinstance(value, str):
                parsed = _parse_datetime(value)
                if parsed is not None:
                    return parsed
    return None


def _derive_migration_id(metadata: dict[str, Any]) -> str | None:
    keys = ("migration_id", "migration_guid", "id", "guid")
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    migration = metadata.get("migration")
    if isinstance(migration, dict):
        for key in keys:
            value = migration.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def load_github_migration_archive(path: str | Path) -> LoadedGitHubArchive:
    archive_path = Path(path).expanduser().resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"Archive file not found: {archive_path}")

    digest = hashlib.sha256()
    with archive_path.open("rb") as file_obj:
        while True:
            chunk = file_obj.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    archive_hash = digest.hexdigest()

    records: list[ArchiveRecord] = []
    metadata_candidates: list[dict[str, Any]] = []

    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            if not member.name.endswith((".json", ".jsonl", ".ndjson")):
                continue

            parsed = _read_json_member(archive, member)
            if parsed is None:
                continue

            family = _canonical_family_for_member(member.name)
            if family in SUPPORTED_FAMILIES:
                for payload in _iter_objects(parsed, family):
                    records.append(
                        ArchiveRecord(
                            family=family,
                            member_path=member.name,
                            payload=payload,
                        )
                    )
                continue

            if Path(member.name).stem.lower().replace("-", "_") in _METADATA_FILENAMES:
                if isinstance(parsed, dict):
                    metadata_candidates.append(parsed)

    migration_metadata = _extract_migration_metadata(metadata_candidates)
    snapshot_timestamp = _derive_snapshot_timestamp(migration_metadata)
    migration_id = _derive_migration_id(migration_metadata)

    metadata = ArchiveMetadata(
        archive_path=str(archive_path),
        archive_hash=archive_hash,
        snapshot_timestamp=snapshot_timestamp,
        migration_id=migration_id,
        migration_metadata=migration_metadata,
    )
    return LoadedGitHubArchive(metadata=metadata, records=records)


def summarize_archive_records(records: list[ArchiveRecord]) -> dict[str, Any]:
    by_family: dict[str, int] = {family: 0 for family in SUPPORTED_FAMILIES}
    for record in records:
        by_family[record.family] = by_family.get(record.family, 0) + 1

    return {
        "total_records": len(records),
        "by_family": by_family,
        "included_families": [family for family, count in by_family.items() if count > 0],
    }
