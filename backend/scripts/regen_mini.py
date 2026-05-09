"""Regenerate a mini in-place by re-running the synthesis pipeline.

Examples:
  uv run python scripts/regen_mini.py alliecatowo
  uv run python scripts/regen_mini.py alliecatowo --force-github-refresh
  uv run python scripts/regen_mini.py alliecatowo --force-github-reingest
  uv run python scripts/regen_mini.py alliecatowo --mode full --json
"""

from __future__ import annotations

import asyncio
import argparse
from datetime import datetime, timezone
import json
import os
import sys
import uuid
from typing import Any

from sqlalchemy import delete, select

from app.db import async_session
from app.models.ingestion_data import IngestionData
from app.models.mini import Mini
from app.plugins.loader import load_plugins
from app.models.schemas import PipelineEvent
from app.synthesis.pipeline import run_pipeline

TERMINAL_MINI_STATUSES = {"ready", "failed"}
RUN_HISTORY_LIMIT = 20


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regenerate a mini in place.")
    parser.add_argument("username", help="Mini username to regenerate")
    parser.add_argument(
        "--mode",
        choices=("incremental", "fresh", "full"),
        default="incremental",
        help=(
            "Operator mode shorthand. incremental=default run, fresh=clear GitHub cache, "
            "full=force GitHub full reingest."
        ),
    )
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
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional operator-provided run identifier. Defaults to a generated id.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Optional hard timeout in seconds for the pipeline run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print final run summary as JSON.",
    )
    return parser.parse_args(argv)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _emit_progress(event: PipelineEvent, *, run_id: str) -> None:
    pct = int(event.progress * 100)
    suffix = f" [error_code={event.error_code}]" if event.error_code else ""
    print(
        (
            f"[{_timestamp()}] [run_id={run_id}] "
            f"[{event.stage}] {event.status} ({pct:>3}%) - {event.message}{suffix}"
        ),
        flush=True,
    )


def _parse_sources(raw: str) -> list[str]:
    sources = [s.strip() for s in raw.split(",") if s.strip()]
    return sources or ["github", "claude_code"]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_failure_reason(metadata_json: Any) -> str | None:
    metadata = _as_dict(metadata_json)
    value = metadata.get("failure_reason")
    return str(value) if isinstance(value, str) and value.strip() else None


def _map_terminal_stop_reason(mini_status: str, failure_reason: str | None) -> str | None:
    if mini_status == "ready":
        return "completed"
    if mini_status != "failed":
        return None
    reason = (failure_reason or "").upper()
    if "TOKEN_BUDGET_EXCEEDED" in reason:
        return "token_budget_exceeded"
    if "TIMEOUT_EXCEEDED" in reason:
        return "timeout_exceeded"
    if "INTERRUPTED_SIGNAL" in reason:
        return "interrupted_signal"
    if "CANCELLED_BY_OPERATOR" in reason:
        return "cancelled_by_operator"
    if "FETCH_" in reason:
        return "failed_fetch"
    if "EXPLORE_" in reason:
        return "failed_explore"
    if "SYNTHESIZE_" in reason:
        return "failed_synthesize"
    if "SAVE_" in reason:
        return "failed_save"
    return "precondition_failed"


def _ingest_cli_meta_with_run(
    metadata_json: Any,
    *,
    run_summary: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(_as_dict(metadata_json))
    ingest_cli = _as_dict(metadata.get("ingest_cli"))
    existing_runs = ingest_cli.get("runs")
    runs: list[dict[str, Any]] = []
    if isinstance(existing_runs, list):
        runs = [entry for entry in existing_runs if isinstance(entry, dict)]

    run_id = str(run_summary.get("run_id") or "")
    if run_id:
        runs = [entry for entry in runs if str(entry.get("run_id") or "") != run_id]
    runs.append(run_summary)
    runs = runs[-RUN_HISTORY_LIMIT:]

    metadata["ingest_cli"] = {
        "schema_version": 1,
        "latest_run": run_summary,
        "runs": runs,
        # TODO(MINI): move run contracts + source stop telemetry to a durable run table.
        "persistence": "mini.metadata_json_scaffold",
    }
    return metadata


async def _mark_terminal_failure(
    mini_id: str,
    *,
    reason: str,
) -> None:
    async with async_session() as session:
        mini = (await session.execute(select(Mini).where(Mini.id == mini_id))).scalars().first()
        if not mini:
            return
        metadata = _as_dict(mini.metadata_json)
        metadata["failure_reason"] = reason
        mini.status = "failed"
        mini.metadata_json = metadata
        await session.commit()


async def _persist_run_summary(mini_id: str, run_summary: dict[str, Any]) -> None:
    async with async_session() as session:
        mini = (await session.execute(select(Mini).where(Mini.id == mini_id))).scalars().first()
        if not mini:
            return
        mini.metadata_json = _ingest_cli_meta_with_run(mini.metadata_json, run_summary=run_summary)
        await session.commit()


def _resolve_mode_overrides(
    mode: str,
    *,
    force_github_refresh: bool,
    force_github_reingest: bool,
) -> tuple[bool, bool]:
    if mode == "fresh" and not force_github_reingest:
        force_github_refresh = True
    if mode == "full":
        force_github_reingest = True
    if force_github_reingest:
        force_github_refresh = True
    return force_github_refresh, force_github_reingest


async def main(
    username: str,
    *,
    mode: str = "incremental",
    force_github_refresh: bool = False,
    force_github_reingest: bool = False,
    sources: list[str] | None = None,
    freshness_mode: str = "replace",
    run_id: str | None = None,
    timeout_seconds: int | None = None,
    json_output: bool = False,
) -> int:
    load_plugins()
    force_github_refresh, force_github_reingest = _resolve_mode_overrides(
        mode,
        force_github_refresh=force_github_refresh,
        force_github_reingest=force_github_reingest,
    )
    source_names = sources or ["github", "claude_code"]
    force_full_sources = {"github"} if force_github_reingest else set()
    run_id = run_id or f"ingest-{uuid.uuid4().hex[:12]}"
    started_at = _utcnow()

    async with async_session() as session:
        result = await session.execute(select(Mini).where(Mini.username == username))
        mini = result.scalars().first()
        if not mini:
            print(f"No mini found for {username}", file=sys.stderr)
            return 1
        owner_id = mini.owner_id
        mini_id = mini.id
        start_stub = {
            "run_id": run_id,
            "username": username,
            "mini_id": mini_id,
            "status": "running",
            "started_at": _iso(started_at),
            "mode": mode,
            "sources": source_names,
            "freshness_mode": freshness_mode,
            "force_full_sources": sorted(force_full_sources),
        }
        mini.metadata_json = _ingest_cli_meta_with_run(mini.metadata_json, run_summary=start_stub)
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

    print(f"[{_timestamp()}] [run_id={run_id}] Regenerating {username} (mini_id={mini_id})", flush=True)
    print(
        (
            f"[{_timestamp()}] [run_id={run_id}] "
            f"provider={os.environ.get('DEFAULT_PROVIDER', 'gemini')} "
            f"mode={mode} sources={source_names} freshness_mode={freshness_mode} "
            f"force_full_sources={sorted(force_full_sources)} timeout_seconds={timeout_seconds}"
        ),
        flush=True,
    )
    timed_out = False
    interrupted = False

    async def _progress(event: PipelineEvent) -> None:
        await _emit_progress(event, run_id=run_id or "unknown")

    try:
        if timeout_seconds and timeout_seconds > 0:
            await asyncio.wait_for(
                run_pipeline(
                    username,
                    async_session,
                    on_progress=_progress,
                    sources=source_names,
                    owner_id=owner_id,
                    mini_id=mini_id,
                    freshness_mode=freshness_mode,
                    force_full_sources=force_full_sources,
                ),
                timeout=timeout_seconds,
            )
        else:
            await run_pipeline(
                username,
                async_session,
                on_progress=_progress,
                sources=source_names,
                owner_id=owner_id,
                mini_id=mini_id,
                freshness_mode=freshness_mode,
                force_full_sources=force_full_sources,
            )
    except asyncio.TimeoutError:
        timed_out = True
        await _mark_terminal_failure(
            mini_id,
            reason=f"TIMEOUT_EXCEEDED: run exceeded timeout_seconds={timeout_seconds}",
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        interrupted = True
        await _mark_terminal_failure(
            mini_id,
            reason="INTERRUPTED_SIGNAL: operator interrupted local ingest run",
        )

    async with async_session() as session:
        mini = (await session.execute(select(Mini).where(Mini.id == mini_id))).scalars().first()

    if not mini:
        print(
            f"[{_timestamp()}] [run_id={run_id}] Failed to load mini after pipeline run.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    failure_reason = _extract_failure_reason(mini.metadata_json)
    terminal_stop_reason = _map_terminal_stop_reason(mini.status, failure_reason)
    if timed_out:
        terminal_stop_reason = "timeout_exceeded"
    if interrupted:
        terminal_stop_reason = "interrupted_signal"

    finished_at = _utcnow()
    duration_seconds = round((finished_at - started_at).total_seconds(), 3)
    run_summary: dict[str, Any] = {
        "run_id": run_id,
        "username": username,
        "mini_id": mini_id,
        "status": mini.status,
        "terminal": mini.status in TERMINAL_MINI_STATUSES,
        "terminal_stop_reason": terminal_stop_reason,
        "failure_reason": failure_reason,
        "started_at": _iso(started_at),
        "finished_at": _iso(finished_at),
        "duration_seconds": duration_seconds,
        "mode": mode,
        "sources": source_names,
        "freshness_mode": freshness_mode,
        "force_full_sources": sorted(force_full_sources),
        "timeout_seconds": timeout_seconds,
    }
    await _persist_run_summary(mini_id, run_summary)

    if json_output:
        print(json.dumps(run_summary, indent=2, sort_keys=True), flush=True)
    else:
        print(
            (
                f"[{_timestamp()}] [run_id={run_id}] "
                f"Pipeline terminal status={mini.status} "
                f"terminal_stop_reason={terminal_stop_reason or 'running'} "
                f"duration_seconds={duration_seconds}"
            ),
            flush=True,
        )

    if terminal_stop_reason == "completed":
        return 0
    if terminal_stop_reason == "timeout_exceeded":
        return 124
    if terminal_stop_reason == "interrupted_signal":
        return 130
    return 2


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    freshness_mode = "append" if args.resume else args.freshness_mode
    sys.exit(
        asyncio.run(
            main(
                args.username,
                mode=args.mode,
                force_github_refresh=args.force_github_refresh,
                force_github_reingest=args.force_github_reingest,
                sources=_parse_sources(args.sources),
                freshness_mode=freshness_mode,
                run_id=args.run_id,
                timeout_seconds=args.timeout,
                json_output=args.json,
            )
        )
    )
