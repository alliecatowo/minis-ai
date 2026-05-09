"""Manual GitHub migration archive ingest (phase 1 bootstrap).

Usage:
  uv run python scripts/ingest_github_archive.py <mini_username> --path /path/export.tar.gz
  uv run python scripts/ingest_github_archive.py <mini_username> --path /path/export.tar.gz --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import select

from app.db import async_session
from app.ingestion.delta import get_latest_external_ids
from app.models.mini import Mini
from app.plugins.base import EvidenceItem
from app.plugins.sources.github_archive import GitHubArchiveSource
from app.synthesis.pipeline import _store_evidence_items_in_db


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest a local GitHub migration archive into evidence.")
    parser.add_argument("username", help="Mini username")
    parser.add_argument("--path", required=True, help="Path to GitHub migration .tar.gz archive")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and summarize normalized items without writing DB rows.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable summary JSON.",
    )
    return parser.parse_args(argv)


def summarize_evidence_items(items: list[EvidenceItem]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_family: dict[str, int] = {}
    for item in items:
        by_type[item.item_type] = by_type.get(item.item_type, 0) + 1
        family = "unknown"
        if isinstance(item.metadata, dict) and isinstance(item.metadata.get("archive_family"), str):
            family = item.metadata["archive_family"]
        by_family[family] = by_family.get(family, 0) + 1

    provenance = items[0].provenance if items else {}
    if not isinstance(provenance, dict):
        provenance = {}

    return {
        "total_items": len(items),
        "by_item_type": dict(sorted(by_type.items())),
        "by_archive_family": dict(sorted(by_family.items())),
        "archive_hash": provenance.get("archive_hash"),
        "snapshot_timestamp": provenance.get("snapshot_timestamp"),
        "migration_id": provenance.get("migration_id"),
    }


async def _run(username: str, archive_path: str, *, dry_run: bool, json_output: bool) -> int:
    source = GitHubArchiveSource(archive_path=archive_path)

    async with async_session() as session:
        mini = (await session.execute(select(Mini).where(Mini.username == username))).scalars().first()
        if not mini:
            print(f"No mini found for username '{username}'", file=sys.stderr)
            return 1
        since_external_ids = await get_latest_external_ids(session, mini.id, source.name)

        items: list[EvidenceItem] = []
        async for item in source.fetch_items(
            identifier=username,
            mini_id=mini.id,
            session=session,
            since_external_ids=since_external_ids,
        ):
            items.append(item)

    summary = summarize_evidence_items(items)
    summary["username"] = username
    summary["source_type"] = source.name
    summary["dry_run"] = dry_run

    if dry_run:
        summary["inserted"] = 0
        summary["updated"] = 0
    else:
        inserted, updated = await _store_evidence_items_in_db(
            mini_id=mini.id,
            source_name=source.name,
            items=items,
            session_factory=async_session,
            username=username,
        )
        summary["inserted"] = inserted
        summary["updated"] = updated

    if json_output:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(
            (
                f"Archive ingest summary for {username} ({source.name})\n"
                f"  dry_run={summary['dry_run']}\n"
                f"  total_items={summary['total_items']} inserted={summary['inserted']} "
                f"updated={summary['updated']}\n"
                f"  archive_hash={summary.get('archive_hash')}\n"
                f"  snapshot_timestamp={summary.get('snapshot_timestamp')}\n"
                f"  migration_id={summary.get('migration_id')}\n"
                f"  by_item_type={summary['by_item_type']}\n"
                f"  by_archive_family={summary['by_archive_family']}"
            )
        )

    return 0


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    raise SystemExit(
        asyncio.run(
            _run(
                username=args.username,
                archive_path=args.path,
                dry_run=args.dry_run,
                json_output=args.json,
            )
        )
    )
