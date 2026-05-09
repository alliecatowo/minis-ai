"""Lightweight post-ingest sanity checks for a mini.

Examples:
  uv run python scripts/ingest_quick_check.py alliecatowo
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import sys

from sqlalchemy import func, select

from app.db import async_session
from app.models.evidence import Evidence, ExplorerProgress
from app.models.mini import Mini


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run lightweight post-ingest checks.")
    parser.add_argument("username", help="Mini username")
    return parser.parse_args(argv)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")


def _check_line(label: str, passed: bool, details: str) -> bool:
    state = "PASS" if passed else "FAIL"
    print(f"[{state}] {label}: {details}", flush=True)
    return passed


async def _run(username: str) -> int:
    async with async_session() as session:
        mini = (
            await session.execute(select(Mini).where(Mini.username == username))
        ).scalars().first()
        if not mini:
            print(f"[{_ts()}] No mini found for {username}", file=sys.stderr, flush=True)
            return 1

        evidence_total = await session.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.mini_id == mini.id)
        )
        github_evidence = await session.scalar(
            select(func.count()).select_from(Evidence).where(
                Evidence.mini_id == mini.id, Evidence.source_type == "github"
            )
        )
        latest_fetched = await session.scalar(
            select(func.max(Evidence.last_fetched_at)).where(Evidence.mini_id == mini.id)
        )
        github_progress = (
            await session.execute(
                select(ExplorerProgress).where(
                    ExplorerProgress.mini_id == mini.id,
                    ExplorerProgress.source_type == "github",
                )
            )
        ).scalars().first()
        github_stop_rows = await session.scalar(
            select(func.count()).select_from(Evidence).where(
                Evidence.mini_id == mini.id,
                Evidence.source_type == "github",
                Evidence.item_type == "ingestion_stop_reason",
            )
        )

    print(f"[{_ts()}] Quick ingest check for {username} (mini_id={mini.id})", flush=True)
    print(
        "Summary: "
        f"status={mini.status} last_pipeline_run_at={mini.last_pipeline_run_at} "
        f"evidence_total={evidence_total or 0} github_evidence={github_evidence or 0} "
        f"github_stop_reason_items={github_stop_rows or 0} latest_fetched={latest_fetched}",
        flush=True,
    )

    checks = [
        _check_line("mini status", mini.status == "ready", f"status={mini.status}"),
        _check_line(
            "pipeline timestamp",
            mini.last_pipeline_run_at is not None,
            f"last_pipeline_run_at={mini.last_pipeline_run_at}",
        ),
        _check_line("evidence exists", (evidence_total or 0) > 0, f"count={evidence_total or 0}"),
        _check_line(
            "github evidence exists",
            (github_evidence or 0) > 0,
            f"github_count={github_evidence or 0}",
        ),
        _check_line(
            "github explorer completed",
            github_progress is not None and github_progress.status == "completed",
            f"progress_status={github_progress.status if github_progress else 'missing'}",
        ),
        _check_line(
            "mini artifacts present",
            bool(mini.system_prompt and mini.spirit_content and mini.memory_content),
            "system_prompt/spirit_content/memory_content must be non-empty",
        ),
    ]

    ok = all(checks)
    print(
        f"[{_ts()}] QUICK CHECK {'PASSED' if ok else 'FAILED'} for {username}",
        flush=True,
    )
    return 0 if ok else 2


if __name__ == "__main__":
    parsed = _parse_args(sys.argv[1:])
    sys.exit(asyncio.run(_run(parsed.username)))
