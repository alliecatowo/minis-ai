"""Render EvalReport as a Markdown document with score tables and summaries."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from eval.judge import SubjectSummary, TurnScore
from eval.runner import EvalReport


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a simple Markdown table."""
    sep = " | ".join("---" for _ in headers)
    header_row = " | ".join(headers)
    lines = [f"| {header_row} |", f"| {sep} |"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _score_badge(score: int) -> str:
    """Return a text badge for a numeric score."""
    if score >= 5:
        return f"**{score}** 🟢"
    elif score >= 4:
        return f"**{score}** 🟡"
    elif score >= 3:
        return f"{score} 🟠"
    else:
        return f"{score} 🔴"


def _format_rubric_breakdown(ts: TurnScore) -> str:
    """Format rubric scores as a compact inline string."""
    if ts.failed:
        return f"ERROR: {ts.error}"
    items = [f"{rs.criterion}={rs.score}" for rs in ts.scorecard.rubric_scores]
    return "; ".join(items) if items else "—"


def _format_review_breakdown(ts: TurnScore) -> str:
    """Format held-out review agreement as a compact inline string."""
    if ts.review_agreement is None:
        return "—"

    agreement = ts.review_agreement
    verdict = "match" if agreement.verdict_match else "miss"
    return (
        f"{agreement.overall_agreement:.2f} "
        f"(verdict={verdict}; blockers_f1={agreement.blocker_f1:.2f}; "
        f"comments_f1={agreement.comment_f1:.2f})"
    )


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_detail_table(summary: SubjectSummary, include_review: bool = False) -> str:
    """Render the per-turn detail table for one subject."""
    headers = ["Turn", "Overall", "Voice", "Factual", "Rubric Breakdown"]
    if include_review:
        headers.append("Review Agreement")
    headers.append("Rationale")
    rows = []
    for ts in summary.turn_scores:
        if ts.failed:
            row = [f"`{ts.turn_id}`", "—", "—", "—", f"*{ts.error}*"]
            if include_review:
                row.append("—")
            row.append("—")
            rows.append(row)
        else:
            row = [
                f"`{ts.turn_id}`",
                _score_badge(ts.scorecard.overall_score),
                _score_badge(ts.scorecard.voice_match),
                _score_badge(ts.scorecard.factual_accuracy),
                _format_rubric_breakdown(ts),
            ]
            if include_review:
                row.append(_format_review_breakdown(ts))
            row.append(ts.scorecard.overall_rationale)
            rows.append(row)
    return _md_table(headers, rows)


def _render_subject_section(summary: SubjectSummary, include_review: bool = False) -> str:
    lines: list[str] = []
    lines.append(f"## Subject: `{summary.subject}`\n")
    lines.append(
        f"**Averages** — Overall: {summary.avg_overall:.1f} | "
        f"Voice: {summary.avg_voice:.1f} | "
        f"Factual: {summary.avg_factual:.1f}"
    )
    if include_review:
        lines[-1] += f" | Review: {summary.avg_review_agreement:.2f}\n"
    else:
        lines[-1] += "\n"

    weak = summary.weak_rubric_items()
    if weak:
        lines.append(
            f"**Consistently weak rubric items (≤2):** {', '.join(f'`{w}`' for w in weak)}\n"
        )

    lines.append(_render_detail_table(summary, include_review=include_review))
    lines.append("")
    return "\n".join(lines)


def _render_summary_table(report: EvalReport) -> str:
    """Render a one-row-per-subject summary table."""
    include_review = any(
        ts.review_agreement is not None
        for summary in report.summaries
        for ts in summary.turn_scores
    )
    headers = ["Subject", "Turns", "Avg Overall", "Avg Voice", "Avg Factual"]
    if include_review:
        headers.append("Avg Review")
    headers.append("Weak Items")
    rows = []
    for summary in report.summaries:
        total = len(summary.turn_scores)
        failed = sum(1 for ts in summary.turn_scores if ts.failed)
        turn_label = f"{total - failed}/{total}"
        weak = summary.weak_rubric_items()
        row = [
            f"`{summary.subject}`",
            turn_label,
            f"{summary.avg_overall:.1f}",
            f"{summary.avg_voice:.1f}",
            f"{summary.avg_factual:.1f}",
        ]
        if include_review:
            row.append(f"{summary.avg_review_agreement:.2f}")
        row.append(", ".join(f"`{w}`" for w in weak) if weak else "—")
        rows.append(row)
    return _md_table(headers, rows)


# ---------------------------------------------------------------------------
# Regression guard
# ---------------------------------------------------------------------------


def _check_regression(report: EvalReport, prior_report_path: Path | None) -> str | None:
    """Compare current report against a prior JSON report.

    Returns a warning string if regression detected, None otherwise.
    """
    if not prior_report_path or not prior_report_path.exists():
        return None

    try:
        prior_data = json.loads(prior_report_path.read_text())
        prior_avg = float(prior_data.get("overall_avg", 0))
    except (json.JSONDecodeError, ValueError, KeyError):
        return None

    current_avg = report.overall_avg()
    delta = current_avg - prior_avg

    if delta < -0.3:
        return (
            f"> **REGRESSION DETECTED** — overall average dropped from "
            f"{prior_avg:.2f} to {current_avg:.2f} (delta: {delta:+.2f}). "
            f"Review changes before merging."
        )
    elif delta > 0.3:
        return (
            f"> **IMPROVEMENT DETECTED** — overall average improved from "
            f"{prior_avg:.2f} to {current_avg:.2f} (delta: {delta:+.2f})."
        )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_report(
    report: EvalReport,
    prior_report_path: Path | None = None,
) -> str:
    """Render the full Markdown report string.

    Args:
        report: The EvalReport to render.
        prior_report_path: Optional path to a prior JSON report for regression comparison.

    Returns:
        Full Markdown string suitable for writing to a .md file.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []

    lines.append("# Minis Fidelity Evaluation Report\n")
    lines.append(f"_Generated: {now}_\n")
    if report.base_url:
        lines.append(f"_Target: `{report.base_url}`_\n")
    if report.model_used:
        lines.append(f"_Judge model: `{report.model_used}`_\n")
    lines.append("")

    # Regression check
    regression_note = _check_regression(report, prior_report_path)
    if regression_note:
        lines.append(regression_note)
        lines.append("")

    # Overall summary table
    lines.append("## Summary\n")
    lines.append(_render_summary_table(report))
    lines.append("")
    lines.append(f"**Overall average: {report.overall_avg():.2f}/5**\n")

    # Per-subject detail sections
    lines.append("---\n")
    include_review = any(
        ts.review_agreement is not None
        for summary in report.summaries
        for ts in summary.turn_scores
    )
    for summary in report.summaries:
        lines.append(_render_subject_section(summary, include_review=include_review))

    return "\n".join(lines)


def report_to_json(report: EvalReport) -> dict:
    """Serialize an EvalReport to a JSON-compatible dict for machine consumption."""
    subjects = []
    for summary in report.summaries:
        turns = []
        for ts in summary.turn_scores:
            turn_data: dict = {
                "subject": ts.subject,
                "turn_id": ts.turn_id,
                "prompt": ts.prompt,
                "mini_response": ts.mini_response,
                "error": ts.error,
            }
            if not ts.failed:
                turn_data["scorecard"] = {
                    "overall_score": ts.scorecard.overall_score,
                    "voice_match": ts.scorecard.voice_match,
                    "factual_accuracy": ts.scorecard.factual_accuracy,
                    "overall_rationale": ts.scorecard.overall_rationale,
                    "rubric_scores": [
                        {
                            "criterion": rs.criterion,
                            "score": rs.score,
                            "rationale": rs.rationale,
                        }
                        for rs in ts.scorecard.rubric_scores
                    ],
                }
                if ts.scorecard.review_selection is not None:
                    turn_data["scorecard"]["review_selection"] = (
                        ts.scorecard.review_selection.model_dump()
                    )
            if ts.review_agreement is not None:
                turn_data["review_agreement"] = ts.review_agreement.model_dump()
            turns.append(turn_data)

        subjects.append(
            {
                "subject": summary.subject,
                "avg_overall": summary.avg_overall,
                "avg_voice": summary.avg_voice,
                "avg_factual": summary.avg_factual,
                "avg_review_agreement": summary.avg_review_agreement,
                "turns": turns,
            }
        )

    return {
        "base_url": report.base_url,
        "model_used": report.model_used,
        "overall_avg": report.overall_avg(),
        "subjects": subjects,
    }
