#!/usr/bin/env python3
"""Manual/nightly live sandbox e2e for the Minis GitHub App.

The script creates a disposable PR in an allowlisted sandbox repository,
exercises both requested-reviewer and @mini mention flows, then polls GitHub for
the App's review/comment output. It is intentionally not suitable for default
PR CI because it creates live GitHub resources and may trigger LLM calls.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"
BOT_SIGNATURE = "using the Minis backend review-prediction API"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxConfig:
    token: str
    repo: str
    allowed_repo: str
    reviewer: str
    mini_username: str
    bot_login: str | None
    timeout_seconds: int
    keep_pr: bool

    @property
    def owner(self) -> str:
        return self.repo.split("/", 1)[0]

    @property
    def repo_name(self) -> str:
        return self.repo.split("/", 1)[1]


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def load_config() -> SandboxConfig:
    repo = _required_env("GH_APP_SANDBOX_REPO")
    allowed_repo = _required_env("GH_APP_SANDBOX_ALLOWED_REPO")
    if repo != allowed_repo:
        raise ConfigError(
            "Refusing to run against non-allowlisted repository. "
            "Set GH_APP_SANDBOX_ALLOWED_REPO to the exact sandbox repo."
        )
    if "/" not in repo:
        raise ConfigError("GH_APP_SANDBOX_REPO must use owner/repo format")

    timeout_raw = os.environ.get("LIVE_GH_APP_E2E_TIMEOUT_SECONDS", "360").strip()
    try:
        timeout_seconds = int(timeout_raw)
    except ValueError as exc:
        raise ConfigError("LIVE_GH_APP_E2E_TIMEOUT_SECONDS must be an integer") from exc

    return SandboxConfig(
        token=_required_env("GH_APP_SANDBOX_TOKEN"),
        repo=repo,
        allowed_repo=allowed_repo,
        reviewer=_required_env("GH_APP_SANDBOX_REVIEWER"),
        mini_username=_required_env("GH_APP_SANDBOX_MINI_USERNAME"),
        bot_login=os.environ.get("GH_APP_BOT_LOGIN", "").strip() or None,
        timeout_seconds=timeout_seconds,
        keep_pr=os.environ.get("LIVE_GH_APP_E2E_KEEP_PR", "").strip().lower()
        in {"1", "true", "yes"},
    )


def admin_action_message(error: Exception) -> str:
    return (
        f"{error}\n\n"
        "Admin action: configure repository Actions secrets/variables for the live sandbox lane:\n"
        "- GH_APP_SANDBOX_TOKEN: fine-grained token with contents/pull-requests write on the sandbox repo.\n"
        "- GH_APP_SANDBOX_REPO and GH_APP_SANDBOX_ALLOWED_REPO: the same owner/repo sandbox value.\n"
        "- GH_APP_SANDBOX_REVIEWER: a human GitHub username with an existing ready mini.\n"
        "- GH_APP_SANDBOX_MINI_USERNAME: username used for @username-mini mention tests.\n"
        "- GH_APP_BOT_LOGIN: optional expected GitHub App bot login, e.g. minis-ai[bot]."
    )


class GitHubClient:
    def __init__(self, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=GITHUB_API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._client.request(method, path, **kwargs)
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            reset = response.headers.get("x-ratelimit-reset", "unknown")
            raise RuntimeError(
                f"GitHub API rate limit exhausted while calling {path}; reset epoch={reset}."
            )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()


def _is_expected_bot(item: dict[str, Any], bot_login: str | None) -> bool:
    user = item.get("user") or {}
    if bot_login:
        return user.get("login") == bot_login
    return user.get("type") == "Bot"


def _has_mini_signature(body: str, username: str) -> bool:
    return f"Review by @{username}'s mini" in body and BOT_SIGNATURE in body


async def _poll_until(
    *,
    timeout_seconds: int,
    interval_seconds: int,
    probe,
    description: str,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_count = 0
    while time.monotonic() < deadline:
        result, count = await probe()
        last_count = count
        if result:
            return result
        await asyncio.sleep(interval_seconds)
    raise TimeoutError(f"Timed out waiting for {description}; inspected {last_count} candidate(s).")


async def create_sandbox_pr(client: GitHubClient, cfg: SandboxConfig, run_id: str) -> dict[str, Any]:
    repo = await client.request("GET", f"/repos/{cfg.repo}")
    default_branch = repo["default_branch"]
    ref = await client.request("GET", f"/repos/{cfg.repo}/git/ref/heads/{default_branch}")
    base_sha = ref["object"]["sha"]

    branch = f"minis-live-e2e/{run_id}"
    await client.request(
        "POST",
        f"/repos/{cfg.repo}/git/refs",
        json={"ref": f"refs/heads/{branch}", "sha": base_sha},
    )

    content = (
        f"# Minis live GitHub App e2e\n\n"
        f"Run id: `{run_id}`\n"
        "This file is created by the manual/nightly sandbox workflow.\n"
    )
    path = f"sandbox/live-e2e/{run_id}.md"
    await client.request(
        "PUT",
        f"/repos/{cfg.repo}/contents/{path}",
        json={
            "message": f"MINI-12 live GitHub App sandbox e2e {run_id}",
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        },
    )

    pr = await client.request(
        "POST",
        f"/repos/{cfg.repo}/pulls",
        json={
            "title": f"MINI-12 live GitHub App sandbox e2e {run_id}",
            "head": branch,
            "base": default_branch,
            "body": (
                "Disposable PR for live GitHub App sandbox e2e.\n\n"
                "Expected: requested-reviewer flow posts a Minis review and "
                "@mini mention flow posts a Minis PR comment."
            ),
        },
    )
    pr["sandbox_branch"] = branch
    return pr


async def request_reviewer(client: GitHubClient, cfg: SandboxConfig, pr_number: int) -> None:
    try:
        await client.request(
            "POST",
            f"/repos/{cfg.repo}/pulls/{pr_number}/requested_reviewers",
            json={"reviewers": [cfg.reviewer]},
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {403, 422}:
            raise RuntimeError(
                "Failed to request the sandbox reviewer. Admin action: ensure "
                "GH_APP_SANDBOX_REVIEWER is a collaborator who can be requested on "
                f"{cfg.repo} and has a ready mini named {cfg.reviewer}."
            ) from exc
        raise


async def wait_for_requested_review(
    client: GitHubClient, cfg: SandboxConfig, pr_number: int
) -> dict[str, Any]:
    async def probe() -> tuple[dict[str, Any] | None, int]:
        reviews = await client.request("GET", f"/repos/{cfg.repo}/pulls/{pr_number}/reviews")
        for review in reviews:
            body = review.get("body") or ""
            if _is_expected_bot(review, cfg.bot_login) and _has_mini_signature(body, cfg.reviewer):
                return review, len(reviews)
        return None, len(reviews)

    return await _poll_until(
        timeout_seconds=cfg.timeout_seconds,
        interval_seconds=10,
        probe=probe,
        description="requested-reviewer Minis PR review",
    )


async def post_mention_comment(client: GitHubClient, cfg: SandboxConfig, pr_number: int) -> dict[str, Any]:
    return await client.request(
        "POST",
        f"/repos/{cfg.repo}/issues/{pr_number}/comments",
        json={
            "body": (
                f"@{cfg.mini_username}-mini please review this PR for the live "
                "GitHub App sandbox e2e."
            )
        },
    )


async def wait_for_mention_response(
    client: GitHubClient,
    cfg: SandboxConfig,
    pr_number: int,
    mention_comment_id: int,
) -> dict[str, Any]:
    async def probe() -> tuple[dict[str, Any] | None, int]:
        comments = await client.request("GET", f"/repos/{cfg.repo}/issues/{pr_number}/comments")
        candidates = [comment for comment in comments if comment.get("id", 0) > mention_comment_id]
        for comment in candidates:
            body = comment.get("body") or ""
            if _is_expected_bot(comment, cfg.bot_login) and _has_mini_signature(
                body, cfg.mini_username
            ):
                return comment, len(candidates)
        return None, len(candidates)

    return await _poll_until(
        timeout_seconds=cfg.timeout_seconds,
        interval_seconds=10,
        probe=probe,
        description="@mini mention response",
    )


async def cleanup_pr(client: GitHubClient, cfg: SandboxConfig, pr: dict[str, Any]) -> None:
    pr_number = pr["number"]
    branch = pr["sandbox_branch"]
    await client.request(
        "PATCH",
        f"/repos/{cfg.repo}/pulls/{pr_number}",
        json={"state": "closed"},
    )
    await client.request("DELETE", f"/repos/{cfg.repo}/git/refs/heads/{branch}")


async def run_live_sandbox_e2e(cfg: SandboxConfig, run_id: str) -> dict[str, Any]:
    client = GitHubClient(cfg.token)
    pr: dict[str, Any] | None = None
    try:
        pr = await create_sandbox_pr(client, cfg, run_id)
        await request_reviewer(client, cfg, pr["number"])
        requested_review = await wait_for_requested_review(client, cfg, pr["number"])
        mention = await post_mention_comment(client, cfg, pr["number"])
        mention_response = await wait_for_mention_response(client, cfg, pr["number"], mention["id"])
        return {
            "repo": cfg.repo,
            "pr_number": pr["number"],
            "pr_url": pr["html_url"],
            "requested_review_id": requested_review.get("id"),
            "mention_comment_id": mention_response.get("id"),
            "kept_pr": cfg.keep_pr,
        }
    finally:
        if pr is not None and not cfg.keep_pr:
            await cleanup_pr(client, cfg, pr)
        await client.close()


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Run the live GitHub App sandbox e2e.")
    parser.add_argument("--preflight-only", action="store_true", help="Validate config and exit.")
    parser.add_argument(
        "--run-id",
        default=os.environ.get("GITHUB_RUN_ID") or str(int(time.time())),
        help="Unique run id used in branch/file names.",
    )
    args = parser.parse_args()

    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"::error::{admin_action_message(exc)}")
        return 2

    if args.preflight_only:
        print(json.dumps({"status": "preflight_ok", "repo": cfg.repo}, indent=2))
        return 0

    try:
        result = await run_live_sandbox_e2e(cfg, args.run_id)
    except Exception as exc:
        print(f"::error::{admin_action_message(exc)}")
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
