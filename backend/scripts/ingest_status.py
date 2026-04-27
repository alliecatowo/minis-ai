"""Show ingest/regeneration status for a mini.

Examples:
  uv run python scripts/ingest_status.py alliecatowo
  uv run python scripts/ingest_status.py alliecatowo --watch --interval 10
  uv run python scripts/ingest_status.py alliecatowo --json
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import sys
from typing import Any

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
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Optional run identifier from regen_mini --run-id. "
            "Falls back to latest run snapshot when omitted."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print status snapshot as JSON.",
    )
    return parser.parse_args(argv)


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")


def _fmt_dt(value: datetime | None) -> str:
    return value.isoformat() if value else "-"


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


def _selected_run_contract(metadata_json: Any, run_id: str | None) -> dict[str, Any] | None:
    metadata = _as_dict(metadata_json)
    ingest_cli = _as_dict(metadata.get("ingest_cli"))
    latest_run = _as_dict(ingest_cli.get("latest_run"))
    runs = ingest_cli.get("runs")
    if not run_id:
        return latest_run or None
    if isinstance(runs, list):
        for run in runs:
            if isinstance(run, dict) and str(run.get("run_id") or "") == run_id:
                return run
    if latest_run and str(latest_run.get("run_id") or "") == run_id:
        return latest_run
    return None


def _stop_rows_contract(
    rows: list[tuple[dict[str, Any] | None, datetime | None, str | None]],
    *,
    run_id: str | None,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for metadata_json, created_at, external_id in rows:
        metadata = _as_dict(metadata_json)
        if run_id and str(metadata.get("run_id") or "") != run_id:
            # TODO(MINI): emit run_id into ingestion_stop_reason evidence rows during FETCH.
            continue
        phase = str(metadata.get("phase") or "unknown")
        reason = str(metadata.get("stop_reason") or "unknown")
        entries.append(
            {
                "phase": phase,
                "stop_reason": reason,
                "created_at": _fmt_dt(created_at),
                "external_id": external_id,
            }
        )
    reason_counts: dict[str, int] = {}
    for entry in entries:
        reason = entry["stop_reason"]
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    latest = entries[0] if entries else None
    return {
        "count": len(entries),
        "latest": latest,
        "reason_counts": reason_counts,
        "entries": entries[:25],
    }


def _build_terminal_contract(
    mini_status: str,
    *,
    failure_reason: str | None,
    stop_contract: dict[str, Any],
) -> dict[str, Any]:
    terminal_stop_reason = _map_terminal_stop_reason(mini_status, failure_reason)
    source_terminal = _as_dict(stop_contract.get("latest"))
    return {
        "is_terminal": mini_status in TERMINAL_MINI_STATUSES,
        "status": mini_status,
        "stop_reason_code": terminal_stop_reason,
        "failure_reason": failure_reason,
        "source_stop_reason": (
            {
                "phase": source_terminal.get("phase"),
                "stop_reason": source_terminal.get("stop_reason"),
                "created_at": source_terminal.get("created_at"),
            }
            if source_terminal
            else None
        ),
    }


async def _collect_snapshot(username: str, *, requested_run_id: str | None) -> tuple[bool, dict[str, Any]]:
    async with async_session() as session:
        mini = (
            await session.execute(select(Mini).where(Mini.username == username))
        ).scalars().first()
        if not mini:
            print(f"[{_ts()}] No mini found for {username}", file=sys.stderr, flush=True)
            return False, {}

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
        github_stop_rows_count = await session.scalar(
            select(func.count()).select_from(Evidence).where(
                Evidence.mini_id == mini.id,
                Evidence.source_type == "github",
                Evidence.item_type == "ingestion_stop_reason",
            )
        )
        github_stop_rows = (
            await session.execute(
                select(Evidence.metadata_json, Evidence.created_at, Evidence.external_id)
                .where(
                    Evidence.mini_id == mini.id,
                    Evidence.source_type == "github",
                    Evidence.item_type == "ingestion_stop_reason",
                )
                .order_by(Evidence.created_at.desc())
                .limit(200)
            )
        ).all()

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

    selected_run = _selected_run_contract(mini.metadata_json, requested_run_id)
    selected_run_id = str((selected_run or {}).get("run_id") or requested_run_id or "")
    stop_contract = _stop_rows_contract(github_stop_rows, run_id=selected_run_id or None)
    if stop_contract["count"] == 0 and selected_run_id:
        # Backward-compat fallback for old rows that do not carry run_id metadata.
        stop_contract = _stop_rows_contract(github_stop_rows, run_id=None)

    github_meta = (mini.metadata_json or {}).get("github", {}) if isinstance(mini.metadata_json, dict) else {}
    failure_reason = _extract_failure_reason(mini.metadata_json)
    terminal_contract = _build_terminal_contract(
        mini.status,
        failure_reason=failure_reason,
        stop_contract=stop_contract,
    )
    snapshot: dict[str, Any] = {
        "as_of": _fmt_dt(datetime.now(timezone.utc)),
        "mini": {
            "id": mini.id,
            "username": username,
            "status": mini.status,
            "updated_at": _fmt_dt(mini.updated_at),
            "last_pipeline_run_at": _fmt_dt(mini.last_pipeline_run_at),
        },
        "run": {
            "requested_run_id": requested_run_id,
            "resolved_run_id": selected_run_id or None,
            "contract": selected_run,
            "terminal": terminal_contract,
        },
        "counts": {
            "evidence_total": evidence_total or 0,
            "evidence_explored": evidence_explored or 0,
            "findings_total": findings_total or 0,
            "quotes_total": quotes_total or 0,
            "github_cache_rows": github_cache_count or 0,
            "github_cache_latest": _fmt_dt(github_cache_latest),
            "github_stop_reason_items": github_stop_rows_count or 0,
        },
        "github_run_flags": {
            "forced_full_reingest": github_meta.get("forced_full_reingest", False),
            "items_total": github_meta.get("items_total", 0),
            "items_skipped": github_meta.get("items_skipped", 0),
            "source_stop_summary": stop_contract,
        },
        "evidence_by_source": [
            {
                "source_type": source_type,
                "count": count,
                "latest_created": _fmt_dt(latest_created),
                "latest_fetched": _fmt_dt(latest_fetched),
            }
            for source_type, count, latest_created, latest_fetched in by_source
        ],
        "explorer_progress": [
            {
                "source_type": row.source_type,
                "status": row.status,
                "explored_items": row.explored_items,
                "total_items": row.total_items,
                "findings_count": row.findings_count,
                "quotes_count": row.quotes_count,
                "nodes_count": row.nodes_count,
                "started_at": _fmt_dt(row.started_at),
                "finished_at": _fmt_dt(row.finished_at),
            }
            for row in progress_rows
        ],
    }
    return True, snapshot


def _render_text_snapshot(snapshot: dict[str, Any]) -> bool:
    mini = _as_dict(snapshot.get("mini"))
    counts = _as_dict(snapshot.get("counts"))
    run = _as_dict(snapshot.get("run"))
    terminal = _as_dict(run.get("terminal"))
    github_run_flags = _as_dict(snapshot.get("github_run_flags"))
    source_stop_summary = _as_dict(github_run_flags.get("source_stop_summary"))
    source_stop_latest = _as_dict(source_stop_summary.get("latest"))

    print(f"[{_ts()}] Ingest status for {mini.get('username')}", flush=True)
    print(
        (
            f"  mini_id={mini.get('id')} status={mini.get('status')} "
            f"updated_at={mini.get('updated_at')} last_pipeline_run_at={mini.get('last_pipeline_run_at')}"
        ),
        flush=True,
    )
    print(
        (
            f"  run_id={run.get('resolved_run_id') or '-'} "
            f"terminal_stop_reason={terminal.get('stop_reason_code') or '-'} "
            f"failure_reason={terminal.get('failure_reason') or '-'}"
        ),
        flush=True,
    )
    if source_stop_latest:
        print(
            (
                "  source_terminal_stop_reason="
                f"{source_stop_latest.get('phase')}:{source_stop_latest.get('stop_reason')} "
                f"at={source_stop_latest.get('created_at')}"
            ),
            flush=True,
        )
    else:
        print("  source_terminal_stop_reason=-", flush=True)
    print(
        (
            f"  evidence_total={counts.get('evidence_total', 0)} "
            f"evidence_explored={counts.get('evidence_explored', 0)} "
            f"findings_total={counts.get('findings_total', 0)} quotes_total={counts.get('quotes_total', 0)}"
        ),
        flush=True,
    )
    print(
        (
            f"  github_cache_rows={counts.get('github_cache_rows', 0)} "
            f"github_cache_latest={counts.get('github_cache_latest', '-')}"
        ),
        flush=True,
    )
    print(
        "  github_run_flags="
        f"forced_full_reingest={github_run_flags.get('forced_full_reingest', False)} "
        f"items_total={github_run_flags.get('items_total', 0)} "
        f"items_skipped={github_run_flags.get('items_skipped', 0)} "
        f"stop_reason_items={counts.get('github_stop_reason_items', 0)}",
        flush=True,
    )

    by_source = snapshot.get("evidence_by_source")
    if isinstance(by_source, list) and by_source:
        print("  evidence_by_source:", flush=True)
        for row in by_source:
            if not isinstance(row, dict):
                continue
            print(
                (
                    f"    - {row.get('source_type')}: count={row.get('count')} "
                    f"latest_created={row.get('latest_created')} "
                    f"latest_fetched={row.get('latest_fetched')}"
                ),
                flush=True,
            )
    else:
        print("  evidence_by_source: none", flush=True)

    progress_rows = snapshot.get("explorer_progress")
    if isinstance(progress_rows, list) and progress_rows:
        print("  explorer_progress:", flush=True)
        for row in progress_rows:
            if not isinstance(row, dict):
                continue
            print(
                "    - "
                f"{row.get('source_type')}: status={row.get('status')} "
                f"explored={row.get('explored_items')}/{row.get('total_items')} "
                f"findings={row.get('findings_count')} quotes={row.get('quotes_count')} nodes={row.get('nodes_count')} "
                f"started_at={row.get('started_at')} finished_at={row.get('finished_at')}",
                flush=True,
            )
    else:
        print("  explorer_progress: none", flush=True)

    return bool(terminal.get("is_terminal"))


async def _run(args: argparse.Namespace) -> int:
    ok, snapshot = await _collect_snapshot(args.username, requested_run_id=args.run_id)
    if not ok:
        return 1
    if args.json:
        print(json.dumps(snapshot, indent=2, sort_keys=True), flush=True)
        terminal = bool(_as_dict(_as_dict(snapshot.get("run")).get("terminal")).get("is_terminal"))
    else:
        terminal = _render_text_snapshot(snapshot)
    if not args.watch:
        return 0

    while not terminal:
        await asyncio.sleep(max(1, args.interval))
        print("", flush=True)
        ok, snapshot = await _collect_snapshot(args.username, requested_run_id=args.run_id)
        if not ok:
            return 1
        if args.json:
            print(json.dumps(snapshot, indent=2, sort_keys=True), flush=True)
            terminal = bool(_as_dict(_as_dict(snapshot.get("run")).get("terminal")).get("is_terminal"))
        else:
            terminal = _render_text_snapshot(snapshot)
    return 0


if __name__ == "__main__":
    parsed = _parse_args(sys.argv[1:])
    sys.exit(asyncio.run(_run(parsed)))
