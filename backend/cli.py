"""Minis CLI — dev convenience tool for managing minis locally."""

import json
import os
import sqlite3
import sys
import time

import httpx
import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table
from rich.text import Text as RichText

# Add backend to path to allow importing app
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from sqlalchemy import select
from app.db import async_session
from app.models.mini import Mini
from app.models.evidence import ReviewCycle

API_BASE = "http://localhost:8000/api"
DB_PATH = os.path.join(os.getcwd(), "minis.db")

app = typer.Typer(help="Minis CLI — manage your developer personality clones.")
db_app = typer.Typer(help="Database operations.")
app.add_typer(db_app, name="db")

console = Console()


def _auth_headers() -> dict[str, str]:
    """Get auth headers from MINIS_TOKEN env var."""
    token = os.environ.get("MINIS_TOKEN", "")
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


@app.command("list")
def list_minis():
    """List all minis in a table."""
    try:
        resp = httpx.get(f"{API_BASE}/minis", timeout=10)
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]API error: {e.response.status_code}[/red]")
        raise typer.Exit(1)

    minis = resp.json()
    if not minis:
        console.print("[dim]No minis found.[/dim]")
        return

    table = Table(title="Minis")
    table.add_column("ID", style="dim")
    table.add_column("Username", style="cyan bold")
    table.add_column("Display Name")
    table.add_column("Status")
    table.add_column("Created")

    for m in minis:
        status = m["status"]
        if status == "ready":
            status_str = "[green]ready[/green]"
        elif status == "processing":
            status_str = "[yellow]processing[/yellow]"
        elif status == "failed":
            status_str = "[red]failed[/red]"
        else:
            status_str = status

        created = m.get("created_at", "")[:19].replace("T", " ")
        table.add_row(
            str(m["id"]),
            m["username"],
            m.get("display_name") or "",
            status_str,
            created,
        )

    console.print(table)


@app.command("get")
def get_mini(username: str):
    """Show mini details as pretty JSON."""
    try:
        resp = httpx.get(f"{API_BASE}/minis/by-username/{username}", timeout=10)
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print(f"[red]Mini '{username}' not found.[/red]")
        else:
            console.print(f"[red]API error: {e.response.status_code}[/red]")
        raise typer.Exit(1)

    data = resp.json()
    console.print(JSON(json.dumps(data, indent=2, default=str)))


@app.command("create")
def create_mini(
    username: str,
    sources: list[str] = typer.Option(
        ["github", "claude_code"], "--source", "-s", help="Ingestion sources to use"
    ),
):
    """Create a mini via the API and poll until ready."""
    try:
        resp = httpx.post(
            f"{API_BASE}/minis",
            json={"username": username, "sources": sources},
            headers=_auth_headers(),
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]API error: {e.response.status_code} — {e.response.text}[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]Creating mini for '{username}'...[/yellow]")

    # Poll until ready or failed
    while True:
        time.sleep(3)
        try:
            poll = httpx.get(f"{API_BASE}/minis/by-username/{username}", timeout=10)
            poll.raise_for_status()
        except httpx.HTTPError:
            console.print(".", end="")
            continue

        data = poll.json()
        status = data.get("status", "unknown")

        if status == "ready":
            console.print(f"\n[green]Mini '{username}' is ready![/green]")
            console.print(f"  Display name: {data.get('display_name', 'N/A')}")
            console.print(f"  Bio: {(data.get('bio') or 'N/A')[:100]}")
            return
        elif status == "failed":
            console.print(f"\n[red]Mini '{username}' failed to create.[/red]")
            raise typer.Exit(1)
        else:
            console.print(".", end="", style="dim")
            sys.stdout.flush()


def _precision_recall_f1(
    expected_ids: set[str],
    predicted_ids: set[str],
) -> tuple[float, float, float]:
    """Compute strict agreement metrics."""
    if not expected_ids and not predicted_ids:
        return 1.0, 1.0, 1.0
    if not expected_ids or not predicted_ids:
        # If expected is empty but predicted is not: Precision=0, Recall=1, F1=0
        # If expected is not empty but predicted is: Precision=1, Recall=0, F1=0
        if not expected_ids:
            return 0.0, 1.0, 0.0
        else:
            return 1.0, 0.0, 0.0

    true_positives = len(expected_ids & predicted_ids)
    precision = true_positives / len(predicted_ids)
    recall = true_positives / len(expected_ids)
    f1 = 0.0
    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def _calculate_metrics(cycles: list[ReviewCycle]) -> dict[str, float]:
    if not cycles:
        return {}

    total = len(cycles)
    approval_matches = 0
    blocker_precisions = []
    blocker_recalls = []
    comment_f1s = []

    for cycle in cycles:
        pred = cycle.predicted_state or {}
        human = cycle.human_review_outcome or {}

        # 1. Approval State Accuracy
        pred_verdict = pred.get("expressed_feedback", {}).get("approval_state")
        human_verdict = human.get("expressed_feedback", {}).get("approval_state")
        if pred_verdict == human_verdict:
            approval_matches += 1

        # 2. Blocker Precision/Recall
        pred_blockers = pred.get("private_assessment", {}).get("blocking_issues", [])
        human_blockers = human.get("private_assessment", {}).get("blocking_issues", [])

        def _to_set(items):
            return set(
                str(i.get("id") if isinstance(i, dict) else i).lower().strip() for i in items
            )

        p_set = _to_set(pred_blockers)
        h_set = _to_set(human_blockers)

        prec, rec, _ = _precision_recall_f1(h_set, p_set)
        blocker_precisions.append(prec)
        blocker_recalls.append(rec)

        # 3. Comment F1
        pred_comments = pred.get("expressed_feedback", {}).get("comments", [])
        human_comments = human.get("expressed_feedback", {}).get("comments", [])

        def _to_comm_set(items):
            return set(
                str(i.get("body") if isinstance(i, dict) else i).lower().strip() for i in items
            )

        p_comm_set = _to_comm_set(pred_comments)
        h_comm_set = _to_comm_set(human_comments)
        _, _, f1 = _precision_recall_f1(h_comm_set, p_comm_set)
        comment_f1s.append(f1)

    return {
        "count": float(total),
        "approval_accuracy": approval_matches / total,
        "blocker_precision": sum(blocker_precisions) / len(blocker_precisions),
        "blocker_recall": sum(blocker_recalls) / len(blocker_recalls),
        "comment_f1": sum(comment_f1s) / len(comment_f1s),
    }


@app.command("agreement")
def show_agreement(username: str):
    """Show Moat Proof agreement metrics for a mini."""

    async def _run():
        async with async_session() as session:
            # Get mini
            stmt = select(Mini).where(Mini.username == username.lower())
            result = await session.execute(stmt)
            mini = result.scalar_one_or_none()

            if not mini:
                console.print(f"[red]Mini '{username}' not found.[/red]")
                raise typer.Exit(1)

            # Get cycles with human outcome
            cycle_stmt = (
                select(ReviewCycle)
                .where(ReviewCycle.mini_id == mini.id)
                .where(ReviewCycle.human_review_outcome.isnot(None))
                .order_by(ReviewCycle.predicted_at.asc())
            )
            cycle_result = await session.execute(cycle_stmt)
            cycles = list(cycle_result.scalars().all())

            if not cycles:
                console.print(
                    f"[yellow]No review cycles with human outcomes found for {username}.[/yellow]"
                )
                return

            total_metrics = _calculate_metrics(cycles)

            # Trend calculation: split in two halves
            n = len(cycles)
            if n >= 2:
                mid = n // 2
                first_half = _calculate_metrics(cycles[:mid])
                recent_half = _calculate_metrics(cycles[mid:])
            else:
                first_half = None
                recent_half = None

            table = Table(
                title=f"Moat Proof: {mini.username}", show_header=True, header_style="bold magenta"
            )
            table.add_column("Metric", style="cyan")
            table.add_column("Score", justify="right")
            table.add_column("Trend", justify="center")

            def format_score(val: float) -> str:
                return f"{val:.1%}"

            def get_trend(metric_key: str) -> str:
                if not first_half or not recent_half:
                    return "[dim]—[/dim]"

                diff = recent_half[metric_key] - first_half[metric_key]
                if abs(diff) < 0.001:
                    return "[dim]→[/dim]"
                elif diff > 0:
                    return f"[green]↑ +{diff:.1%}[/green]"
                else:
                    return f"[red]↓ {diff:.1%}[/red]"

            metrics_to_show = [
                ("Approval Accuracy", "approval_accuracy"),
                ("Blocker Precision", "blocker_precision"),
                ("Blocker Recall", "blocker_recall"),
                ("Comment F1", "comment_f1"),
            ]

            for label, key in metrics_to_show:
                table.add_row(label, format_score(total_metrics[key]), get_trend(key))

            console.print(
                Panel(
                    RichText.assemble(
                        ("Mini: ", "dim"),
                        (f"{mini.username}\n", "bold cyan"),
                        ("Cycles: ", "dim"),
                        (f"{len(cycles)}", "bold white"),
                    ),
                    title="Mini Agreement Dashboard",
                    border_style="blue",
                )
            )
            console.print(table)

    import asyncio

    try:
        asyncio.run(_run())
    except Exception as e:
        console.print(f"[red]Error fetching metrics: {e}[/red]")
        raise typer.Exit(1)


@app.command("delete")
def delete_mini(username: str):
    """Delete a mini directly from the SQLite database."""
    if not os.path.exists(DB_PATH):
        console.print("[red]Database file not found.[/red]")
        raise typer.Exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM minis WHERE username = ?", (username.lower(),))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()

    if deleted:
        console.print(f"[green]Deleted mini '{username}'.[/green]")
    else:
        console.print(f"[yellow]Mini '{username}' not found in database.[/yellow]")


@app.command("recreate")
def recreate_mini(
    username: str,
    sources: list[str] = typer.Option(
        ["github", "claude_code"], "--source", "-s", help="Ingestion sources to use"
    ),
):
    """Delete and recreate a mini."""
    delete_mini(username)
    create_mini(username, sources=sources)


@app.command("chat")
def chat_with_mini(username: str):
    """Interactive terminal chat with a mini via SSE streaming."""
    # Verify mini exists and is ready
    try:
        resp = httpx.get(f"{API_BASE}/minis/by-username/{username}", timeout=10)
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print("[red]Cannot connect to API. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print(f"[red]Mini '{username}' not found.[/red]")
        else:
            console.print(f"[red]API error: {e.response.status_code}[/red]")
        raise typer.Exit(1)

    data = resp.json()
    if data.get("status") != "ready":
        console.print(f"[red]Mini '{username}' is not ready (status: {data.get('status')}).[/red]")
        raise typer.Exit(1)

    mini_id = data["id"]
    display = data.get("display_name") or username
    console.print(f"[bold cyan]Chatting with {display}[/bold cyan]")
    console.print("[dim]Type 'quit' or 'exit' to end the conversation.[/dim]\n")

    history: list[dict[str, str]] = []

    while True:
        try:
            message = console.input("[bold green]You:[/bold green] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        if message.strip().lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break

        if not message.strip():
            continue

        console.print(f"[bold cyan]{display}:[/bold cyan] ", end="")

        assistant_response = ""
        try:
            with httpx.stream(
                "POST",
                f"{API_BASE}/minis/{mini_id}/chat",
                json={"message": message, "history": history},
                timeout=httpx.Timeout(connect=10, read=120, write=10, pool=10),
            ) as stream:
                for line in stream.iter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        # The SSE events: "token" has text chunks, "done"/"error" are terminal
                        print(chunk, end="", flush=True)
                        assistant_response += chunk
                    elif line.startswith("event: "):
                        event_type = line[7:].strip()
                        if event_type == "done":
                            break
                        elif event_type == "error":
                            break
        except httpx.ReadTimeout:
            console.print("\n[red]Response timed out.[/red]")
            continue
        except httpx.ConnectError:
            console.print("\n[red]Lost connection to API.[/red]")
            break

        print()  # newline after streamed response

        # Append to history for multi-turn
        history.append({"role": "user", "content": message})
        if assistant_response:
            history.append({"role": "assistant", "content": assistant_response})


@db_app.command("reset")
def db_reset():
    """Delete the SQLite database file."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        console.print("[green]Database deleted.[/green]")
    else:
        console.print("[yellow]Database file not found (already clean).[/yellow]")


if __name__ == "__main__":
    app()
