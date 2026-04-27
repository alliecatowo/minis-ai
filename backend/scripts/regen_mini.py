"""Regenerate a mini in-place by re-running the synthesis pipeline.

Examples:
  uv run python scripts/regen_mini.py alliecatowo
  uv run python scripts/regen_mini.py alliecatowo --force-github-refresh
  uv run python scripts/regen_mini.py alliecatowo --force-github-reingest
"""

from __future__ import annotations

import asyncio
import argparse
from datetime import datetime, timezone
import os
import sys

from sqlalchemy import delete, select

from app.db import async_session
from app.models.ingestion_data import IngestionData
from app.models.mini import Mini
from app.plugins.loader import load_plugins
from app.models.schemas import PipelineEvent
from app.synthesis.pipeline import run_pipeline


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regenerate a mini in place.")
    parser.add_argument("username", help="Mini username to regenerate")
    parser.add_argument(
        "--force-github-refresh",
        action="store_true",
        help="Delete GitHub ingestion cache rows before pipeline run (cache refresh only).",
    )
    parser.add_argument(
        "--force-github-reingest",
        action="store_true",
        help=(
            "Force true GitHub full reingest by bypassing incremental since_external_ids "
            "for source=github (also clears GitHub ingestion cache rows)."
        ),
    )
    parser.add_argument(
        "--sources",
        default="github,claude_code",
        help="Comma-separated source list (default: github,claude_code).",
    )
    parser.add_argument(
        "--freshness-mode",
        choices=("replace", "append"),
        default="replace",
        help="Explorer freshness mode (default: replace).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume-like mode shorthand; equivalent to --freshness-mode append.",
    )
    return parser.parse_args(argv)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")


async def _emit_progress(event: PipelineEvent) -> None:
    pct = int(event.progress * 100)
    suffix = f" [error_code={event.error_code}]" if event.error_code else ""
    print(
        f"[{_timestamp()}] [{event.stage}] {event.status} ({pct:>3}%) - {event.message}{suffix}",
        flush=True,
    )


def _parse_sources(raw: str) -> list[str]:
    sources = [s.strip() for s in raw.split(",") if s.strip()]
    return sources or ["github", "claude_code"]


async def main(
    username: str,
    *,
    force_github_refresh: bool = False,
    force_github_reingest: bool = False,
    sources: list[str] | None = None,
    freshness_mode: str = "replace",
) -> int:
    load_plugins()
    if force_github_reingest:
        force_github_refresh = True
    source_names = sources or ["github", "claude_code"]
    force_full_sources = {"github"} if force_github_reingest else set()

    async with async_session() as session:
        result = await session.execute(select(Mini).where(Mini.username == username))
        mini = result.scalars().first()
        if not mini:
            print(f"No mini found for {username}", file=sys.stderr)
            return 1
        owner_id = mini.owner_id
        mini_id = mini.id
        if force_github_refresh:
            deleted = await session.execute(
                delete(IngestionData).where(
                    IngestionData.mini_id == mini_id,
                    IngestionData.source_name == "github",
                )
            )
            print(
                f"Cleared GitHub cache rows for {username}: {deleted.rowcount or 0}",
                flush=True,
            )
        mini.status = "processing"
        await session.commit()

    print(f"[{_timestamp()}] Regenerating {username} (mini_id={mini_id})", flush=True)
    print(
        f"[{_timestamp()}] provider={os.environ.get('DEFAULT_PROVIDER', 'gemini')} "
        f"sources={source_names} freshness_mode={freshness_mode} "
        f"force_full_sources={sorted(force_full_sources)}",
        flush=True,
    )
    await run_pipeline(
        username,
        async_session,
        on_progress=_emit_progress,
        sources=source_names,
        owner_id=owner_id,
        mini_id=mini_id,
        freshness_mode=freshness_mode,
        force_full_sources=force_full_sources,
    )
    print(f"[{_timestamp()}] Pipeline complete.", flush=True)
    return 0


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    freshness_mode = "append" if args.resume else args.freshness_mode
    sys.exit(
        asyncio.run(
            main(
                args.username,
                force_github_refresh=args.force_github_refresh,
                force_github_reingest=args.force_github_reingest,
                sources=_parse_sources(args.sources),
                freshness_mode=freshness_mode,
            )
        )
    )
