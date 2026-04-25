#!/usr/bin/env python3
"""Fidelity evaluation CLI entrypoint.

Runs the eval harness against live mini chat endpoints and writes a Markdown
report + machine-readable JSON to disk.

Usage:
    cd backend
    uv run python scripts/run_fidelity_eval.py \\
        --subjects alliecatowo,jlongster,joshwcomeau \\
        --base-url http://localhost:8000 \\
        --out eval-report.md

    # With auth token (CI / production)
    uv run python scripts/run_fidelity_eval.py \\
        --subjects alliecatowo \\
        --base-url https://minis.fly.dev \\
        --token "$SERVICE_JWT" \\
        --out eval-report.md

    # Compare against prior run for regression detection
    uv run python scripts/run_fidelity_eval.py \\
        --subjects alliecatowo \\
        --prior eval-report.json \\
        --out eval-report-new.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Ensure backend package is importable when running from the backend/ dir
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from eval.report import render_report, report_to_json
from eval.runner import run_eval

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

EVAL_DIR = _backend_dir / "eval"
SUBJECTS_DIR = EVAL_DIR / "subjects"
GOLDEN_TURNS_DIR = EVAL_DIR / "golden_turns"
GOLD_REVIEW_CASES_DIR = EVAL_DIR / "gold_review_cases"


def resolve_subject_files(
    subject_names: list[str],
    *,
    include_gold_review_cases: bool = True,
) -> tuple[list[Path], list[Path]]:
    """Return (subject_files, turn_files) for the given usernames."""
    subject_files: list[Path] = []
    turn_files: list[Path] = []
    missing = []

    for name in subject_names:
        sf = SUBJECTS_DIR / f"{name}.yaml"
        tf = GOLDEN_TURNS_DIR / f"{name}.yaml"
        if not sf.exists():
            missing.append(f"subjects/{name}.yaml")
        if not tf.exists():
            missing.append(f"golden_turns/{name}.yaml")
        if sf.exists():
            subject_files.append(sf)
        if tf.exists():
            turn_files.append(tf)
        if include_gold_review_cases:
            gf = GOLD_REVIEW_CASES_DIR / f"{name}.yaml"
            if gf.exists():
                turn_files.append(gf)

    if missing:
        logger.warning("Missing eval files: %s", ", ".join(missing))

    return subject_files, turn_files


async def main_async(args: argparse.Namespace) -> int:
    subject_names = [s.strip() for s in args.subjects.split(",") if s.strip()]
    if not subject_names:
        logger.error("No subjects specified")
        return 1

    subject_files, turn_files = resolve_subject_files(
        subject_names,
        include_gold_review_cases=not args.no_gold_review_cases,
    )
    if not subject_files:
        logger.error("No valid subject files found for: %s", subject_names)
        return 1

    token = args.token or os.environ.get("SERVICE_JWT")

    logger.info(
        "Running fidelity eval for %d subject(s) against %s",
        len(subject_files),
        args.base_url,
    )

    report = await run_eval(
        subject_files=subject_files,
        turn_files=turn_files,
        base_url=args.base_url,
        token=token,
        judge_model=args.judge_model or None,
    )

    # --- Write Markdown report ---
    out_path = Path(args.out)
    prior_path = Path(args.prior) if args.prior else None
    md_content = render_report(report, prior_report_path=prior_path)
    out_path.write_text(md_content)
    logger.info("Markdown report written to: %s", out_path)

    # --- Write JSON report ---
    json_path = out_path.with_suffix(".json")
    json_data = report_to_json(report)
    json_path.write_text(json.dumps(json_data, indent=2))
    logger.info("JSON report written to: %s", json_path)

    # --- Print summary ---
    overall = report.overall_avg()
    print(f"\nOverall average score: {overall:.2f}/5")
    for summary in report.summaries:
        failed = sum(1 for ts in summary.turn_scores if ts.failed)
        total = len(summary.turn_scores)
        print(
            f"  {summary.subject}: {summary.avg_overall:.1f} overall | "
            f"{summary.avg_voice:.1f} voice | "
            f"{summary.avg_factual:.1f} factual | "
            f"{failed}/{total} failed"
        )

    # Regression exit code
    if prior_path and prior_path.exists():
        try:
            prior_data = json.loads(prior_path.read_text())
            prior_avg = float(prior_data.get("overall_avg", 0))
            delta = overall - prior_avg
            if delta < -0.3:
                logger.warning(
                    "REGRESSION: overall average dropped by %.2f (%.2f -> %.2f)",
                    abs(delta),
                    prior_avg,
                    overall,
                )
                return 2  # Non-zero so CI can detect regression
        except (json.JSONDecodeError, ValueError, KeyError):
            pass

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Minis fidelity evaluation harness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--subjects",
        default="alliecatowo,jlongster,joshwcomeau",
        help="Comma-separated list of subject usernames (default: all three baseline subjects)",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Minis backend base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Bearer auth token. Falls back to SERVICE_JWT env var. Omit for dev bypass.",
    )
    parser.add_argument(
        "--out",
        default="eval-report.md",
        help="Output Markdown file path (default: eval-report.md). JSON written alongside.",
    )
    parser.add_argument(
        "--prior",
        default=None,
        help="Path to prior JSON report for regression comparison.",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Override judge model (PydanticAI model string, e.g. 'anthropic:claude-sonnet-4-6'). "
        "Defaults to STANDARD tier model.",
    )
    parser.add_argument(
        "--no-gold-review-cases",
        action="store_true",
        help="Do not append structured gold review-prediction cases to matching subjects.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
