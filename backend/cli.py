"""Minis CLI — hosted API client for managing minis."""

import json
import os
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote

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
_scripts_dir = os.path.join(_backend_dir, "scripts")

DEFAULT_API_BASE = "https://minis-api.fly.dev/api"
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "minis" / "mcp-token"
MCP_LOGIN_COMMAND = "cd mcp-server && uv run minis-mcp auth login"

app = typer.Typer(help="Minis CLI — manage your developer personality clones via the hosted API.")
ingest_app = typer.Typer(help="Local ingest/regeneration wrappers for operator workflows.")
app.add_typer(ingest_app, name="ingest")

console = Console()


class ReviewAuthorModel(str, Enum):
    junior_peer = "junior_peer"
    trusted_peer = "trusted_peer"
    senior_peer = "senior_peer"
    unknown = "unknown"


class ReviewDeliveryContext(str, Enum):
    hotfix = "hotfix"
    normal = "normal"
    exploratory = "exploratory"
    incident = "incident"


def _auth_headers() -> dict[str, str]:
    """Get auth headers from env tokens or the MCP auth token file."""
    token = _auth_token()
    headers = {"Accept": "application/json"}
    if not token:
        return headers
    headers["Authorization"] = f"Bearer {token}"
    return headers


def _auth_token() -> str:
    env_token = (os.environ.get("MINIS_TOKEN") or os.environ.get("MINIS_AUTH_TOKEN") or "").strip()
    if env_token:
        return env_token

    token_file = Path(os.environ.get("MINIS_AUTH_TOKEN_FILE", str(DEFAULT_TOKEN_PATH))).expanduser()
    try:
        return token_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _auth_token_source() -> str:
    if (os.environ.get("MINIS_TOKEN") or "").strip():
        return "MINIS_TOKEN"
    if (os.environ.get("MINIS_AUTH_TOKEN") or "").strip():
        return "MINIS_AUTH_TOKEN"

    token_file = Path(os.environ.get("MINIS_AUTH_TOKEN_FILE", str(DEFAULT_TOKEN_PATH))).expanduser()
    if token_file.exists():
        return str(token_file)
    return "none"


def _require_auth_token(action: str) -> None:
    if _auth_token():
        return
    console.print(
        f"[red]Authentication required to {action}.[/red] "
        "Set MINIS_TOKEN (or MINIS_AUTH_TOKEN) to a Minis API bearer token, "
        f"or run `{MCP_LOGIN_COMMAND}`."
    )
    raise typer.Exit(1)


def _api_base() -> str:
    """Return the configured API base URL, including the /api prefix."""
    raw = (
        os.environ.get("MINIS_API_BASE")
        or os.environ.get("MINIS_BACKEND_API")
        or os.environ.get("MINIS_BACKEND_URL")
        or DEFAULT_API_BASE
    ).strip()
    if not raw:
        raw = DEFAULT_API_BASE
    raw = raw.rstrip("/")
    if raw.endswith("/api"):
        return raw
    return f"{raw}/api"


def _api(path: str) -> str:
    return f"{_api_base()}{path}"


def _emit_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))


def _http_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return json.dumps(detail)
    return response.text


def _render_api_error(action: str, exc: httpx.HTTPStatusError) -> None:
    detail = _http_error_detail(exc.response)
    status_code = exc.response.status_code
    if status_code == 401:
        console.print(
            f"[red]Authentication failed while trying to {action}.[/red] "
            "Set a valid MINIS_TOKEN (or MINIS_AUTH_TOKEN)."
        )
        if detail:
            console.print(f"[dim]{detail}[/dim]")
        return
    if status_code in {403, 404, 409, 423, 429, 503}:
        console.print(f"[yellow]{action.capitalize()} unavailable:[/yellow] {status_code} {detail}")
        return
    console.print(f"[red]API error while trying to {action}: {status_code} {detail}[/red]")


def _get_json(path: str, *, require_auth: bool = False, timeout: float = 10) -> Any:
    if require_auth:
        _require_auth_token(f"call {path}")
    try:
        resp = httpx.get(_api(path), headers=_auth_headers(), timeout=timeout)
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to Minis API at {_api_base()}.[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        _render_api_error("call Minis API", exc)
        raise typer.Exit(1)
    return resp.json()


def _post_json(
    path: str,
    *,
    payload: dict[str, Any],
    require_auth: bool = False,
    timeout: float = 30,
) -> Any:
    if require_auth:
        _require_auth_token(f"call {path}")
    try:
        resp = httpx.post(
            _api(path),
            json=payload,
            headers=_auth_headers(),
            timeout=timeout,
        )
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to Minis API at {_api_base()}.[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        _render_api_error("call Minis API", exc)
        raise typer.Exit(1)
    return resp.json()


def _delete(path: str, *, require_auth: bool = False, timeout: float = 30) -> None:
    if require_auth:
        _require_auth_token(f"call {path}")
    try:
        resp = httpx.delete(_api(path), headers=_auth_headers(), timeout=timeout)
        resp.raise_for_status()
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to Minis API at {_api_base()}.[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        _render_api_error("call Minis API", exc)
        raise typer.Exit(1)


def _get_mini_by_username(username: str, *, require_auth: bool = False) -> dict[str, Any]:
    data = _get_json(f"/minis/by-username/{quote(username, safe='')}", require_auth=require_auth)
    if not isinstance(data, dict):
        console.print("[red]API returned an invalid mini payload.[/red]")
        raise typer.Exit(1)
    return data


def _get_ready_mini(username: str, action: str, *, require_auth: bool = False) -> dict[str, Any]:
    mini = _get_mini_by_username(username, require_auth=require_auth)
    unavailable_reason = _mini_unavailable_reason(mini, action)
    if unavailable_reason:
        console.print(f"[yellow]{action.capitalize()} unavailable:[/yellow] {unavailable_reason}")
        raise typer.Exit(1)
    return mini


def _mini_unavailable_reason(mini: dict[str, Any], action: str) -> str | None:
    status = mini.get("status")
    if status == "ready":
        return None
    if status in {"processing", "pending"}:
        return f"Mini '{mini.get('username')}' is still processing; {action} is gated until status=ready."
    if status == "failed":
        return f"Mini '{mini.get('username')}' failed during creation; {action} is unavailable."
    return f"Mini '{mini.get('username')}' is not ready (status: {status}); {action} is unavailable."


def _run_git(args: list[str], cwd: str | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return completed.stdout.strip()


def _try_git(args: list[str], cwd: str | None = None) -> str | None:
    try:
        return _run_git(args, cwd=cwd)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def _resolve_repo_name() -> str | None:
    remote_url = _try_git(["remote", "get-url", "origin"])
    if not remote_url:
        return os.path.basename(os.getcwd()) or None

    normalized = remote_url.rstrip("/")
    if "github.com/" in normalized:
        normalized = normalized.split("github.com/", 1)[1]
    elif ":" in normalized and normalized.startswith("git@"):
        normalized = normalized.split(":", 1)[1]

    normalized = normalized.removesuffix(".git").strip("/")
    if "/" not in normalized:
        return os.path.basename(os.getcwd()) or None
    return normalized


def _detect_base_ref() -> str | None:
    candidates = [
        _try_git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]),
        "origin/main",
        "origin/master",
        "main",
        "master",
    ]
    seen: set[str] = set()
    for ref in candidates:
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if _try_git(["rev-parse", "--verify", ref]):
            return ref
    return None


def _run_local_script(script_name: str, args: list[str]) -> None:
    script_path = os.path.join(_scripts_dir, script_name)
    if not os.path.exists(script_path):
        console.print(f"[red]Missing local script:[/red] {script_path}")
        raise typer.Exit(1)

    command = ["uv", "run", "python", f"scripts/{script_name}", *args]
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.setdefault("PYTHONPATH", ".")
    try:
        subprocess.run(
            command,
            cwd=_backend_dir,
            env=env,
            check=True,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]Local runner unavailable:[/red] {exc}")
        raise typer.Exit(1) from exc
    except subprocess.CalledProcessError as exc:
        raise typer.Exit(exc.returncode or 1) from exc


def _parse_sources_csv(raw: str) -> list[str]:
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return parts or ["github", "claude_code"]


def _collect_pre_review_request(
    *,
    base_ref: str | None,
    title: str | None,
    description: str | None,
    author_model: ReviewAuthorModel,
    delivery_context: ReviewDeliveryContext,
) -> tuple[str, dict[str, object]]:
    resolved_base = base_ref or _detect_base_ref()
    if not resolved_base:
        raise RuntimeError(
            "Could not determine a base ref. Pass --base explicitly, for example --base origin/main."
        )

    try:
        merge_base = _run_git(["merge-base", "HEAD", resolved_base])
        changed_files_raw = _run_git(
            ["diff", "--name-only", "--diff-filter=ACMRD", "--find-renames", merge_base]
        )
        untracked_files_raw = _run_git(["ls-files", "--others", "--exclude-standard"])
        diff_summary = _run_git(["diff", "--stat", "--find-renames", merge_base])
        branch_name = _try_git(["branch", "--show-current"]) or "current-branch"
    except FileNotFoundError as exc:
        raise RuntimeError("Git is required for pre-review, but it is not installed.") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(f"Unable to read git diff context: {stderr}") from exc

    changed_files = [line.strip() for line in changed_files_raw.splitlines() if line.strip()]
    untracked_files = [line.strip() for line in untracked_files_raw.splitlines() if line.strip()]
    changed_files = list(dict.fromkeys([*changed_files, *untracked_files]))
    if untracked_files:
        untracked_summary = "Untracked files:\n" + "\n".join(untracked_files[:50])
        diff_summary = "\n\n".join(part for part in [diff_summary, untracked_summary] if part)

    if not changed_files and not diff_summary:
        raise RuntimeError(
            "No local changes found for pre-review. Commit or edit something first, or pass a different --base."
        )

    request = {
        "repo_name": _resolve_repo_name(),
        "title": title or f"Pre-review: {branch_name}",
        "description": description or f"Working tree diff against {resolved_base}.",
        "diff_summary": diff_summary[:50000],
        "changed_files": changed_files[:200],
        "author_model": author_model.value,
        "delivery_context": delivery_context.value,
    }
    return resolved_base, request


def _approval_style(approval_state: str) -> str:
    if approval_state == "approve":
        return "green"
    if approval_state == "comment":
        return "yellow"
    return "red"


def _review_prediction_unavailable_reason(prediction: dict[str, object]) -> str | None:
    required = {"prediction_available", "mode", "unavailable_reason"}
    if not required.issubset(prediction):
        return "backend response omitted review prediction availability contract"

    if prediction.get("prediction_available") is False or prediction.get("mode") == "gated":
        return str(prediction.get("unavailable_reason") or "review prediction is gated")

    if prediction.get("prediction_available") is not True:
        return "backend response returned invalid prediction_available value"
    if prediction.get("mode") != "llm":
        return f"backend response returned unsupported review prediction mode: {prediction.get('mode')}"
    if prediction.get("unavailable_reason") is not None:
        return "backend response returned unavailable_reason for available prediction"
    return None


def _render_pre_review_report(username: str, base_ref: str, prediction: dict[str, object]) -> None:
    unavailable_reason = _review_prediction_unavailable_reason(prediction)
    if unavailable_reason:
        console.print(
            Panel(
                RichText.assemble(
                    ("Mini: ", "dim"),
                    (f"{username}\n", "bold cyan"),
                    ("Base: ", "dim"),
                    (f"{base_ref}\n", "bold white"),
                    ("Prediction: ", "dim"),
                    ("unavailable", "bold yellow"),
                ),
                title="Pre-review gated",
                border_style="yellow",
            )
        )
        console.print(f"[yellow]No review prediction was produced:[/yellow] {unavailable_reason}")
        return

    private_assessment = prediction.get("private_assessment", {})
    expressed_feedback = prediction.get("expressed_feedback", {})
    delivery_policy = prediction.get("delivery_policy", {})
    blockers = private_assessment.get("blocking_issues", []) or []
    open_questions = private_assessment.get("open_questions", []) or []
    approval_state = str(expressed_feedback.get("approval_state") or "unknown")

    summary = expressed_feedback.get("summary") or "No summary returned."
    strictness = delivery_policy.get("strictness") or "unknown"

    console.print(
        Panel(
            RichText.assemble(
                ("Mini: ", "dim"),
                (f"{username}\n", "bold cyan"),
                ("Base: ", "dim"),
                (f"{base_ref}\n", "bold white"),
                ("Likely verdict: ", "dim"),
                (approval_state.replace("_", " "), f"bold {_approval_style(approval_state)}"),
                ("\nStrictness: ", "dim"),
                (str(strictness), "bold white"),
            ),
            title="Pre-review",
            border_style="blue",
        )
    )
    console.print(f"[bold]Summary:[/bold] {summary}")

    if blockers:
        table = Table(title="Likely blockers")
        table.add_column("Key", style="cyan")
        table.add_column("Confidence", justify="right")
        table.add_column("Summary")
        table.add_column("Framework")
        for blocker in blockers:
            confidence = blocker.get("confidence")
            confidence_str = (
                f"{float(confidence):.0%}" if isinstance(confidence, int | float) else "—"
            )
            framework_id = blocker.get("framework_id")
            revision = blocker.get("revision")
            if framework_id:
                if isinstance(revision, int) and revision > 0:
                    framework_str = f"from framework: {framework_id}, validated {revision}×"
                else:
                    framework_str = f"from framework: {framework_id}"
            else:
                framework_str = ""
            table.add_row(
                str(blocker.get("key") or "unknown"),
                confidence_str,
                str(blocker.get("summary") or ""),
                framework_str,
            )
        console.print(table)
    else:
        console.print("[green]No likely blockers surfaced by this mini.[/green]")

    if open_questions:
        console.print("[bold]Open questions:[/bold]")
        for question in open_questions[:5]:
            console.print(f"- {question.get('summary') or question.get('rationale') or 'Unknown question'}")


def _prediction_summary_payload(
    username: str, base_ref: str, prediction: dict[str, object]
) -> dict[str, object]:
    unavailable_reason = _review_prediction_unavailable_reason(prediction)
    payload: dict[str, object] = {
        "username": username,
        "base_ref": base_ref,
        "prediction_available": unavailable_reason is None,
        "unavailable_reason": unavailable_reason,
        "prediction": prediction,
    }
    if unavailable_reason:
        return payload

    private_assessment = prediction.get("private_assessment", {})
    expressed_feedback = prediction.get("expressed_feedback", {})
    if isinstance(private_assessment, dict):
        payload["blocking_issue_count"] = len(private_assessment.get("blocking_issues", []) or [])
        payload["open_question_count"] = len(private_assessment.get("open_questions", []) or [])
    if isinstance(expressed_feedback, dict):
        payload["approval_state"] = expressed_feedback.get("approval_state")
        payload["summary"] = expressed_feedback.get("summary")
    return payload


def _render_patch_advisor_report(username: str, base_ref: str, advisor: dict[str, object]) -> None:
    if advisor.get("advice_available") is False or advisor.get("mode") == "gated":
        reason = advisor.get("unavailable_reason") or "patch advisor is gated"
        console.print(
            Panel(
                RichText.assemble(
                    ("Mini: ", "dim"),
                    (f"{username}\n", "bold cyan"),
                    ("Base: ", "dim"),
                    (f"{base_ref}\n", "bold white"),
                    ("Advisor: ", "dim"),
                    ("unavailable", "bold yellow"),
                ),
                title="Patch advisor gated",
                border_style="yellow",
            )
        )
        console.print(f"[yellow]No patch guidance was produced:[/yellow] {reason}")
        return

    review_prediction = advisor.get("review_prediction", {})
    expressed_feedback = (
        review_prediction.get("expressed_feedback", {})
        if isinstance(review_prediction, dict)
        else {}
    )
    summary = expressed_feedback.get("summary") or "Framework-backed patch guidance."
    console.print(
        Panel(
            RichText.assemble(
                ("Mini: ", "dim"),
                (f"{username}\n", "bold cyan"),
                ("Base: ", "dim"),
                (f"{base_ref}\n", "bold white"),
                ("Mode: ", "dim"),
                (str(advisor.get("mode") or "framework"), "bold white"),
            ),
            title="Patch advisor",
            border_style="blue",
        )
    )
    console.print(f"[bold]Summary:[/bold] {summary}")

    sections = [
        ("Change plan", "change_plan"),
        ("Do not change", "do_not_change"),
        ("Risks", "risks"),
        ("Expected reviewer objections", "expected_reviewer_objections"),
    ]
    for title, key in sections:
        items = advisor.get(key, []) or []
        if not isinstance(items, list) or not items:
            continue
        table = Table(title=title)
        table.add_column("Key", style="cyan")
        table.add_column("Confidence", justify="right")
        table.add_column("Summary")
        table.add_column("Framework")
        for item in items[:8]:
            if not isinstance(item, dict):
                continue
            confidence = item.get("confidence")
            confidence_str = (
                f"{float(confidence):.0%}" if isinstance(confidence, int | float) else "-"
            )
            table.add_row(
                str(item.get("key") or "unknown"),
                confidence_str,
                str(item.get("summary") or ""),
                str(item.get("framework_id") or ""),
            )
        console.print(table)

    evidence_refs = advisor.get("evidence_references", []) or []
    if isinstance(evidence_refs, list) and evidence_refs:
        console.print("[bold]Evidence references:[/bold]")
        for ref in evidence_refs[:5]:
            if not isinstance(ref, dict):
                continue
            evidence_ids = ", ".join(str(item) for item in ref.get("evidence_ids", [])[:3])
            console.print(
                f"- {ref.get('framework_id')}: {evidence_ids or 'no evidence ids'}"
            )


@ingest_app.command("run")
def ingest_run(
    username: str,
    mode: str = typer.Option(
        "incremental",
        "--mode",
        help="Run mode: incremental, fresh, or full.",
    ),
    sources: str = typer.Option(
        "github,claude_code",
        "--sources",
        help="Comma-separated source list for regen_mini.py.",
    ),
    freshness_mode: str = typer.Option(
        "replace",
        "--freshness-mode",
        help="Explorer freshness mode: replace or append.",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Shortcut for freshness_mode=append.",
    ),
    force_github_refresh: bool = typer.Option(
        False,
        "--force-github-refresh",
        help="Clear GitHub ingestion cache rows before run.",
    ),
    force_github_reingest: bool = typer.Option(
        False,
        "--force-github-reingest",
        help="Force true GitHub full reingest for this run.",
    ),
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Optional operator run identifier.",
    ),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        help="Optional hard timeout in seconds.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit run summary JSON."),
):
    """Run local mini regeneration with run-oriented ingest contract output."""
    args: list[str] = [username, "--mode", mode, "--sources", ",".join(_parse_sources_csv(sources))]
    if resume:
        args.append("--resume")
    else:
        args.extend(["--freshness-mode", freshness_mode])
    if force_github_refresh:
        args.append("--force-github-refresh")
    if force_github_reingest:
        args.append("--force-github-reingest")
    if run_id:
        args.extend(["--run-id", run_id])
    if timeout is not None:
        args.extend(["--timeout", str(timeout)])
    if json_output:
        args.append("--json")
    _run_local_script("regen_mini.py", args)


@ingest_app.command("status")
def ingest_status(
    username: str,
    watch: bool = typer.Option(False, "--watch", help="Tail status until terminal mini state."),
    interval: int = typer.Option(10, "--interval", help="Watch interval in seconds."),
    run_id: str | None = typer.Option(None, "--run-id", help="Optional run id to inspect."),
    json_output: bool = typer.Option(False, "--json", help="Emit status payload as JSON."),
):
    """Show local ingest status with run-oriented terminal stop-reason fields."""
    args: list[str] = [username]
    if watch:
        args.append("--watch")
    args.extend(["--interval", str(interval)])
    if run_id:
        args.extend(["--run-id", run_id])
    if json_output:
        args.append("--json")
    _run_local_script("ingest_status.py", args)


@ingest_app.command("full")
def ingest_full(
    username: str,
    sources: str = typer.Option(
        "github,claude_code",
        "--sources",
        help="Comma-separated source list for regen_mini.py.",
    ),
    run_id: str | None = typer.Option(None, "--run-id", help="Optional operator run identifier."),
    timeout: int | None = typer.Option(None, "--timeout", help="Optional hard timeout in seconds."),
    json_output: bool = typer.Option(False, "--json", help="Emit run summary JSON."),
):
    """Run full GitHub reingest mode with local wrappers."""
    args: list[str] = [
        username,
        "--mode",
        "full",
        "--sources",
        ",".join(_parse_sources_csv(sources)),
    ]
    if run_id:
        args.extend(["--run-id", run_id])
    if timeout is not None:
        args.extend(["--timeout", str(timeout)])
    if json_output:
        args.append("--json")
    _run_local_script("regen_mini.py", args)


@ingest_app.command("resume")
def ingest_resume(
    username: str,
    sources: str = typer.Option(
        "github,claude_code",
        "--sources",
        help="Comma-separated source list for regen_mini.py.",
    ),
    run_id: str | None = typer.Option(None, "--run-id", help="Optional operator run identifier."),
    timeout: int | None = typer.Option(None, "--timeout", help="Optional hard timeout in seconds."),
    json_output: bool = typer.Option(False, "--json", help="Emit run summary JSON."),
):
    """Run append/resume mode for local mini regeneration."""
    args: list[str] = [
        username,
        "--mode",
        "incremental",
        "--sources",
        ",".join(_parse_sources_csv(sources)),
        "--resume",
    ]
    if run_id:
        args.extend(["--run-id", run_id])
    if timeout is not None:
        args.extend(["--timeout", str(timeout)])
    if json_output:
        args.append("--json")
    _run_local_script("regen_mini.py", args)


@app.command("list")
def list_minis(
    mine: bool = typer.Option(
        False,
        "--mine",
        help="List minis owned by the authenticated user instead of public minis.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print the raw hosted API payload as JSON."),
):
    """List public minis, or your own minis with --mine."""
    if mine:
        _require_auth_token("list your minis")

    payload = _get_json(f"/minis?mine={'true' if mine else 'false'}", require_auth=mine)
    if json_output:
        _emit_json(payload)
        return

    minis = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(minis, list):
        console.print("[red]API returned an invalid minis list.[/red]")
        raise typer.Exit(1)
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


@app.command("status")
def status(json_output: bool = typer.Option(False, "--json", help="Print status as JSON.")):
    """Show hosted API and shared MCP auth status."""
    health: dict[str, Any] = {
        "api_base": _api_base(),
        "api": "unknown",
        "auth": "not_configured",
        "token_source": _auth_token_source(),
        "user": None,
        "login_command": MCP_LOGIN_COMMAND,
    }

    try:
        response = httpx.get(_api("/health"), headers={"Accept": "application/json"}, timeout=5)
        response.raise_for_status()
        payload = response.json()
        health["api"] = "ok" if payload.get("status") == "ok" else "unexpected"
    except httpx.ConnectError:
        health["api"] = "unreachable"
        health["error"] = f"Cannot connect to Minis API at {_api_base()}."
    except httpx.HTTPStatusError as exc:
        health["api"] = "error"
        health["error"] = f"{exc.response.status_code} {_http_error_detail(exc.response)}"
    except ValueError:
        health["api"] = "error"
        health["error"] = "Health endpoint returned invalid JSON."

    if _auth_token():
        try:
            auth_response = httpx.get(_api("/auth/me"), headers=_auth_headers(), timeout=5)
            auth_response.raise_for_status()
            user = auth_response.json()
            health["auth"] = "authenticated"
            health["user"] = user
        except httpx.HTTPStatusError as exc:
            health["auth"] = "invalid"
            health["auth_error"] = f"{exc.response.status_code} {_http_error_detail(exc.response)}"
        except (httpx.ConnectError, ValueError) as exc:
            health["auth"] = "unknown"
            health["auth_error"] = str(exc)

    if json_output:
        _emit_json(health)
        return

    api_style = "green" if health["api"] == "ok" else "red"
    auth_style = "green" if health["auth"] == "authenticated" else "yellow"
    user = health["user"] if isinstance(health["user"], dict) else {}
    console.print(
        Panel(
            RichText.assemble(
                ("API: ", "dim"),
                (str(health["api"]), f"bold {api_style}"),
                ("\nBase: ", "dim"),
                (str(health["api_base"]), "white"),
                ("\nAuth: ", "dim"),
                (str(health["auth"]), f"bold {auth_style}"),
                ("\nToken source: ", "dim"),
                (str(health["token_source"]), "white"),
            ),
            title="Minis hosted status",
            border_style=api_style,
        )
    )
    if user:
        console.print(
            f"[green]Signed in as[/green] {user.get('github_username') or user.get('id')}"
        )
    elif health["auth"] == "not_configured":
        console.print(f"[yellow]Login needed for private actions:[/yellow] `{MCP_LOGIN_COMMAND}`")
    elif health["auth"] == "invalid":
        console.print(f"[red]Stored token is invalid.[/red] Re-run `{MCP_LOGIN_COMMAND}`.")


@app.command("login")
def login():
    """Show the shared MCP device-auth login command without duplicating it."""
    if _auth_token():
        try:
            user = _get_json("/auth/me", require_auth=True, timeout=5)
        except typer.Exit:
            console.print(f"[red]Stored token is invalid.[/red] Re-run `{MCP_LOGIN_COMMAND}`.")
            raise typer.Exit(1)
        username = user.get("github_username") if isinstance(user, dict) else None
        console.print(f"[green]Already authenticated.[/green] {username or ''}".rstrip())
        return

    console.print("[yellow]Hosted CLI auth is shared with the Minis MCP server.[/yellow]")
    console.print(f"Run: [bold]{MCP_LOGIN_COMMAND}[/bold]")
    console.print("[dim]The CLI will read the token file written by that command.[/dim]")


@app.command("get")
def get_mini(
    username: str,
    json_output: bool = typer.Option(False, "--json", help="Print the raw hosted API payload as JSON."),
):
    """Show mini details as pretty JSON."""
    data = _get_mini_by_username(username)
    if json_output:
        _emit_json(data)
    else:
        console.print(JSON(json.dumps(data, indent=2, default=str)))


@app.command("create")
def create_mini(
    username: str,
    sources: list[str] = typer.Option(
        ["github"], "--source", "-s", help="Hosted ingestion sources to use"
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        help="Poll the hosted API until the mini reaches ready or failed.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print create/status payloads as JSON."),
):
    """Create or regenerate a mini through the hosted API."""
    _require_auth_token("create a mini")
    data = _post_json(
        "/minis",
        payload={"username": username, "sources": sources},
        require_auth=True,
        timeout=30,
    )
    if not isinstance(data, dict):
        console.print("[red]API returned an invalid create response.[/red]")
        raise typer.Exit(1)
    if json_output and not wait:
        _emit_json(data)
        return

    mini_id = data.get("id")
    status = data.get("status", "unknown")
    console.print(
        f"[green]Mini create accepted for '{username}'.[/green] "
        f"status={status} id={mini_id or 'unknown'}"
    )
    if not wait:
        console.print("[dim]Run `minis-cli get {}` to check readiness.[/dim]".format(username))
        return

    if not mini_id:
        console.print("[red]Cannot poll status because the API response omitted mini id.[/red]")
        raise typer.Exit(1)

    while True:
        time.sleep(3)
        poll = _get_json(f"/minis/{mini_id}", require_auth=True, timeout=10)
        if not isinstance(poll, dict):
            console.print("[red]API returned an invalid mini status payload.[/red]")
            raise typer.Exit(1)
        status = poll.get("status", "unknown")
        if status == "ready":
            if json_output:
                _emit_json(poll)
                return
            console.print(f"\n[green]Mini '{username}' is ready.[/green]")
            console.print(f"  Display name: {poll.get('display_name', 'N/A')}")
            console.print(f"  Bio: {(poll.get('bio') or 'N/A')[:100]}")
            return
        if status == "failed":
            if json_output:
                _emit_json(poll)
            console.print(f"\n[red]Mini '{username}' failed to create.[/red]")
            raise typer.Exit(1)
        console.print(".", end="", style="dim")
        sys.stdout.flush()


@app.command("pre-review")
def pre_review(
    username: str,
    base: str | None = typer.Option(
        None,
        "--base",
        help="Git ref to compare your current work against. Defaults to origin HEAD/main/master.",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Optional title override sent to the review-prediction backend.",
    ),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Optional description override sent to the review-prediction backend.",
    ),
    author_model: ReviewAuthorModel = typer.Option(
        ReviewAuthorModel.unknown,
        "--author-model",
        help="How the mini should model your relationship to the author.",
    ),
    context: ReviewDeliveryContext = typer.Option(
        ReviewDeliveryContext.normal,
        "--context",
        help="Delivery context for the predicted review.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print review prediction as JSON."),
):
    """Ask what a mini would likely block on before you request review."""
    try:
        resolved_base, request = _collect_pre_review_request(
            base_ref=base,
            title=title,
            description=description,
            author_model=author_model,
            delivery_context=context,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    mini = _get_ready_mini(username, "pre-review")
    prediction = _post_json(
        f"/minis/{quote(str(mini['id']), safe='')}/review-prediction",
        payload=request,
        timeout=30,
    )
    if not isinstance(prediction, dict):
        console.print("[red]API returned an invalid review prediction payload.[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_json(_prediction_summary_payload(username, resolved_base, prediction))
        return
    _render_pre_review_report(username, resolved_base, prediction)


@app.command("patch-advisor")
def patch_advisor(
    username: str,
    base: str | None = typer.Option(
        None,
        "--base",
        help="Git ref to compare your current work against. Defaults to origin HEAD/main/master.",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Optional title override sent to the patch-advisor backend.",
    ),
    description: str | None = typer.Option(
        None,
        "--description",
        help="Optional description override sent to the patch-advisor backend.",
    ),
    author_model: ReviewAuthorModel = typer.Option(
        ReviewAuthorModel.unknown,
        "--author-model",
        help="How the mini should model your relationship to the author.",
    ),
    context: ReviewDeliveryContext = typer.Option(
        ReviewDeliveryContext.normal,
        "--context",
        help="Delivery context for the patch guidance.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print patch advisor payload as JSON."),
):
    """Ask a mini for framework-backed patch guidance for your local diff."""
    try:
        resolved_base, request = _collect_pre_review_request(
            base_ref=base,
            title=title,
            description=description,
            author_model=author_model,
            delivery_context=context,
        )
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    mini = _get_ready_mini(username, "patch advisor")
    advisor = _post_json(
        f"/minis/{quote(str(mini['id']), safe='')}/patch-advisor",
        payload=request,
        timeout=30,
    )
    if not isinstance(advisor, dict):
        console.print("[red]API returned an invalid patch advisor payload.[/red]")
        raise typer.Exit(1)
    if json_output:
        _emit_json({"username": username, "base_ref": resolved_base, "advisor": advisor})
        return
    _render_patch_advisor_report(username, resolved_base, advisor)


def _format_optional_percent(value: Any) -> str:
    if value is None:
        return "[dim]unavailable[/dim]"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "[dim]unavailable[/dim]"


@app.command("agreement")
def show_agreement(username: str):
    """Show hosted agreement metrics for a mini."""
    _require_auth_token("view agreement metrics")
    mini = _get_mini_by_username(username, require_auth=True)
    mini_id = mini.get("id")
    if not mini_id:
        console.print("[red]API response omitted mini id.[/red]")
        raise typer.Exit(1)

    data = _get_json(
        f"/minis/{quote(str(mini_id), safe='')}/agreement-scorecard-summary",
        require_auth=True,
    )
    if not isinstance(data, dict):
        console.print("[red]API returned an invalid agreement scorecard payload.[/red]")
        raise typer.Exit(1)

    trend = data.get("trend") if isinstance(data.get("trend"), dict) else {}
    direction = trend.get("direction", "unknown")
    delta = trend.get("delta")
    if direction == "up" and delta is not None:
        trend_str = f"[green]↑ +{float(delta):.1%}[/green]"
    elif direction == "down" and delta is not None:
        trend_str = f"[red]↓ {float(delta):.1%}[/red]"
    elif direction == "flat":
        trend_str = "[dim]→[/dim]"
    else:
        trend_str = "[dim]insufficient data[/dim]"

    table = Table(title=f"Moat Proof: {data.get('username', username)}")
    table.add_column("Metric", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Trend", justify="center")
    table.add_row("Approval Accuracy", _format_optional_percent(data.get("approval_accuracy")), trend_str)
    table.add_row("Blocker Precision", _format_optional_percent(data.get("blocker_precision")), trend_str)
    table.add_row("Comment Overlap", _format_optional_percent(data.get("comment_overlap")), trend_str)

    console.print(
        Panel(
            RichText.assemble(
                ("Mini: ", "dim"),
                (f"{data.get('username', username)}\n", "bold cyan"),
                ("Cycles: ", "dim"),
                (f"{data.get('cycles_count', 0)}", "bold white"),
            ),
            title="Mini Agreement Dashboard",
            border_style="blue",
        )
    )
    console.print(table)


@app.command("delete")
def delete_mini(username: str):
    """Delete an owned mini through the hosted API."""
    _require_auth_token("delete a mini")
    mini = _get_mini_by_username(username, require_auth=True)
    mini_id = mini.get("id")
    if not mini_id:
        console.print("[red]API response omitted mini id.[/red]")
        raise typer.Exit(1)
    _delete(f"/minis/{quote(str(mini_id), safe='')}", require_auth=True)
    console.print(f"[green]Deleted mini '{username}'.[/green]")


@app.command("recreate")
def recreate_mini(
    username: str,
    sources: list[str] = typer.Option(
        ["github"], "--source", "-s", help="Hosted ingestion sources to use"
    ),
):
    """Delete and recreate a mini through the hosted API."""
    delete_mini(username)
    create_mini(username, sources=sources)


def _iter_sse_events(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: httpx.Timeout | None = None,
) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    event_type = "message"
    data_lines: list[str] = []

    try:
        with httpx.stream(
            method,
            _api(path),
            json=payload,
            headers={**_auth_headers(), "Accept": "text/event-stream"},
            timeout=timeout
            or httpx.Timeout(connect=10, read=120, write=10, pool=10),
        ) as stream:
            stream.raise_for_status()
            for line in stream.iter_lines():
                if line == "":
                    if data_lines:
                        events.append((event_type, "\n".join(data_lines)))
                    event_type = "message"
                    data_lines = []
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_type = line.removeprefix("event:").strip() or "message"
                    continue
                if line.startswith("data:"):
                    data_lines.append(line.removeprefix("data:").lstrip())
            if data_lines:
                events.append((event_type, "\n".join(data_lines)))
    except httpx.ReadTimeout:
        console.print("\n[red]Response timed out.[/red]")
        raise typer.Exit(1)
    except httpx.ConnectError:
        console.print(f"\n[red]Cannot connect to Minis API at {_api_base()}.[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as exc:
        _render_api_error("chat with mini", exc)
        raise typer.Exit(1)

    return events


def _send_chat_message(
    *,
    mini_id: str,
    display: str,
    message: str,
    history: list[dict[str, str]],
    conversation_id: str | None,
) -> tuple[str | None, str]:
    console.print(f"[bold cyan]{display}:[/bold cyan] ", end="")
    events = _iter_sse_events(
        "POST",
        f"/minis/{quote(mini_id, safe='')}/chat",
        payload={"message": message, "history": history, "conversation_id": conversation_id},
    )

    assistant_response = ""
    resolved_conversation_id = conversation_id
    for event_type, data in events:
        if event_type == "conversation_id":
            resolved_conversation_id = data
            continue
        if event_type == "chunk":
            print(data, end="", flush=True)
            assistant_response += data
            continue
        if event_type == "error":
            console.print(f"\n[yellow]Chat unavailable:[/yellow] {data}")
            raise typer.Exit(1)
    print()
    return resolved_conversation_id, assistant_response


@app.command("chat")
def chat_with_mini(
    username: str,
    message: str | None = typer.Argument(
        None,
        help="Optional one-shot message. Omit for interactive chat.",
    ),
    conversation_id: str | None = typer.Option(
        None,
        "--conversation-id",
        help="Continue an authenticated hosted conversation.",
    ),
):
    """Chat with a mini through hosted SSE streaming."""
    data = _get_ready_mini(username, "chat")

    mini_id = data["id"]
    display = data.get("display_name") or username
    history: list[dict[str, str]] = []
    if message is not None:
        _send_chat_message(
            mini_id=mini_id,
            display=display,
            message=message,
            history=history,
            conversation_id=conversation_id,
        )
        return

    console.print(f"[bold cyan]Chatting with {display}[/bold cyan]")
    console.print("[dim]Type 'quit' or 'exit' to end the conversation.[/dim]\n")

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

        conversation_id, assistant_response = _send_chat_message(
            mini_id=mini_id,
            display=display,
            message=message,
            history=history,
            conversation_id=conversation_id,
        )

        # Append to history for multi-turn
        history.append({"role": "user", "content": message})
        if assistant_response:
            history.append({"role": "assistant", "content": assistant_response})


_FW_HIGH_CONF = 0.7
_FW_LOW_CONF = 0.3


def _confidence_badge(confidence: float, revision: int) -> str:
    """Return display badges for a decision framework based on confidence and revision."""
    parts: list[str] = []
    if confidence > _FW_HIGH_CONF:
        parts.append("[HIGH CONFIDENCE ✓]")
    elif confidence < _FW_LOW_CONF:
        parts.append("[LOW CONFIDENCE ⚠]")
    if revision > 0:
        parts.append(f"[validated {revision} time{'s' if revision != 1 else ''}]")
    return " ".join(parts)


@app.command("decision-frameworks")
def show_decision_frameworks(
    username: str,
    min_confidence: float = typer.Option(0.0, "--min-confidence", help="Minimum confidence threshold (0–1)."),
    limit: int = typer.Option(20, "--limit", help="Maximum number of frameworks to display."),
):
    """Show a mini's hosted decision-framework profile."""
    data = _get_json(
        "/minis/by-username/"
        f"{quote(username, safe='')}/decision-frameworks?limit={limit}&min_confidence={min_confidence}",
    )
    if not isinstance(data, dict):
        console.print("[red]API returned an invalid decision-framework payload.[/red]")
        raise typer.Exit(1)

    raw_frameworks = data.get("frameworks") or []
    if not isinstance(raw_frameworks, list) or not raw_frameworks:
        console.print(
            f"[yellow]No decision frameworks found for '{username}' at "
            f"min-confidence={min_confidence:.2f}.[/yellow]"
        )
        raise typer.Exit(1)

    parsed: list[dict[str, Any]] = []
    for raw in raw_frameworks:
        if not isinstance(raw, dict):
            continue
        try:
            conf = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        try:
            rev = int(raw.get("revision", 0))
        except (TypeError, ValueError):
            rev = 0
        value = raw.get("value") or ""
        if isinstance(value, str):
            value = value.replace("value:", "").replace("_", " ")
        parsed.append(
            {
                "framework_id": raw.get("framework_id") or raw.get("id") or "—",
                "condition": raw.get("trigger") or raw.get("condition") or "",
                "action": raw.get("action") or "",
                "value": value,
                "confidence": conf,
                "revision": rev,
            }
        )

    if not parsed:
        console.print(f"[yellow]No decision frameworks found for '{username}'.[/yellow]")
        raise typer.Exit(1)

    table = Table(
        title=f"Decision Frameworks — {data.get('username', username)}",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Framework", style="cyan", no_wrap=False, max_width=24)
    table.add_column("Trigger -> Action -> Value", no_wrap=False, max_width=52)
    table.add_column("Confidence", justify="right")
    table.add_column("Rev", justify="right")
    table.add_column("Badges", no_wrap=False)

    for fw in parsed:
        action = fw["action"]
        value = fw["value"]
        if action and value:
            tav = f"{fw['condition']} -> {action} -> {value}"
        elif action:
            tav = f"{fw['condition']} -> {action}"
        elif value:
            tav = f"{fw['condition']} -> {value}"
        else:
            tav = fw["condition"] or "-"

        conf = fw["confidence"]
        rev = fw["revision"]
        conf_color = "green" if conf > _FW_HIGH_CONF else ("red" if conf < _FW_LOW_CONF else "yellow")
        badge_str = _confidence_badge(conf, rev)

        table.add_row(
            fw["framework_id"],
            tav,
            f"[{conf_color}]{conf:.0%}[/{conf_color}]",
            str(rev),
            badge_str or "[dim]-[/dim]",
        )

    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    mean_conf = summary.get("mean_confidence")
    max_rev = summary.get("max_revision")
    total = summary.get("total", len(parsed))
    console.print(
        Panel(
            RichText.assemble(
                ("Mini: ", "dim"),
                (f"{data.get('username', username)}\n", "bold cyan"),
                ("Showing: ", "dim"),
                (f"{len(parsed)}", "bold white"),
                (" / ", "dim"),
                (f"{total} frameworks", "white"),
                ("  |  mean confidence: ", "dim"),
                (_format_optional_percent(mean_conf), "bold white"),
                ("  |  max revision: ", "dim"),
                (str(max_rev or 0), "bold white"),
            ),
            title="Decision Framework Profile",
            border_style="blue",
        )
    )
    console.print(table)


if __name__ == "__main__":
    app()
