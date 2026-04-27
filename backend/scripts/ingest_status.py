"""Show ingest/regeneration status for a mini.

Examples:
  uv run python scripts/ingest_status.py alliecatowo
  uv run python scripts/ingest_status.py alliecatowo --watch --interval 10
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import sys

from sqlalchemy import func, select

from app.db import async_session
from app.models.evidence import Evidence, ExplorerFinding, ExplorerProgress, ExplorerQuote
from app.models.ingestion_data import IngestionData
from app.models.mini import Mini


TERMINAL_MINI_STATUSES = {"ready", "failed"}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show ingest status for a mini.")
    parser.add_argument("username", help="Mini username")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Refresh output until the mini reaches a terminal status.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Watch refresh interval in seconds (default: 10).",
    )
    return parser.parse_args(argv)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")


def _fmt_dt(value: datetime | None) -> str:
    return value.isoformat() if value else "-"


async def _render_snapshot(username: str) -> tuple[bool, bool]:
    async with async_session() as session:
        mini = (
            await session.execute(select(Mini).where(Mini.username == username))
        ).scalars().first()
        if not mini:
            print(f"[{_ts()}] No mini found for {username}", file=sys.stderr, flush=True)
            return False, True

        evidence_total = await session.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.mini_id == mini.id)
        )
        evidence_explored = await session.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.mini_id == mini.id, Evidence.explored)
        )
        findings_total = await session.scalar(
            select(func.count()).select_from(ExplorerFinding).where(ExplorerFinding.mini_id == mini.id)
        )
        quotes_total = await session.scalar(
            select(func.count()).select_from(ExplorerQuote).where(ExplorerQuote.mini_id == mini.id)
        )
        github_cache = await session.execute(
            select(func.count(IngestionData.id), func.max(IngestionData.fetched_at)).where(
                IngestionData.mini_id == mini.id,
                IngestionData.source_name == "github",
            )
        )
        github_cache_count, github_cache_latest = github_cache.one()
        github_stop_rows = await session.scalar(
            select(func.count()).select_from(Evidence).where(
                Evidence.mini_id == mini.id,
                Evidence.source_type == "github",
                Evidence.item_type == "ingestion_stop_reason",
            )
        )

        by_source = (
            await session.execute(
                select(
                    Evidence.source_type,
                    func.count(Evidence.id),
                    func.max(Evidence.created_at),
                    func.max(Evidence.last_fetched_at),
                )
                .where(Evidence.mini_id == mini.id)
                .group_by(Evidence.source_type)
                .order_by(Evidence.source_type)
            )
        ).all()

        progress_rows = (
            await session.execute(
                select(ExplorerProgress)
                .where(ExplorerProgress.mini_id == mini.id)
                .order_by(ExplorerProgress.source_type)
            )
        ).scalars().all()

    print(f"[{_ts()}] Ingest status for {username}", flush=True)
    print(
        f"  mini_id={mini.id} status={mini.status} updated_at={_fmt_dt(mini.updated_at)} last_pipeline_run_at={_fmt_dt(mini.last_pipeline_run_at)}",
        flush=True,
    )
    print(
        f"  evidence_total={evidence_total or 0} evidence_explored={evidence_explored or 0} findings_total={findings_total or 0} quotes_total={quotes_total or 0}",
        flush=True,
    )
    print(
        f"  github_cache_rows={github_cache_count or 0} github_cache_latest={_fmt_dt(github_cache_latest)}",
        flush=True,
    )
    github_meta = (mini.metadata_json or {}).get("github", {}) if isinstance(mini.metadata_json, dict) else {}
    print(
        "  github_run_flags="
        f"forced_full_reingest={github_meta.get('forced_full_reingest', False)} "
        f"items_total={github_meta.get('items_total', 0)} "
        f"items_skipped={github_meta.get('items_skipped', 0)} "
        f"stop_reason_items={github_stop_rows or 0}",
        flush=True,
    )
    if by_source:
        print("  evidence_by_source:", flush=True)
        for source_type, count, latest_created, latest_fetched in by_source:
            print(
                f"    - {source_type}: count={count} latest_created={_fmt_dt(latest_created)} latest_fetched={_fmt_dt(latest_fetched)}",
                flush=True,
            )
    else:
        print("  evidence_by_source: none", flush=True)

    if progress_rows:
        print("  explorer_progress:", flush=True)
        for row in progress_rows:
            print(
                "    - "
                f"{row.source_type}: status={row.status} "
                f"explored={row.explored_items}/{row.total_items} "
                f"findings={row.findings_count} quotes={row.quotes_count} nodes={row.nodes_count} "
                f"started_at={_fmt_dt(row.started_at)} finished_at={_fmt_dt(row.finished_at)}",
                flush=True,
            )
    else:
        print("  explorer_progress: none", flush=True)

    is_terminal = mini.status in TERMINAL_MINI_STATUSES
    return True, is_terminal


async def _run(args: argparse.Namespace) -> int:
    ok, terminal = await _render_snapshot(args.username)
    if not ok:
        return 1
    if not args.watch:
        return 0

    while not terminal:
        await asyncio.sleep(max(1, args.interval))
        print("", flush=True)
        ok, terminal = await _render_snapshot(args.username)
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    parsed = _parse_args(sys.argv[1:])
    sys.exit(asyncio.run(_run(parsed)))
