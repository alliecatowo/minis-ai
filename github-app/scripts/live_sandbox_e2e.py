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


class SandboxAPIError(RuntimeError):
    def __init__(self, service: str, method: str, path: str, status_code: int, body: str):
        self.service = service
        self.method = method
        self.path = path
        self.status_code = status_code
        self.body = body
        super().__init__(
            f"{service} API {method} {path} failed with {status_code}: {body[:1000]}"
        )


@dataclass(frozen=True)
class SandboxConfig:
    token: str
    reviewer_token: str
    repo: str
    allowed_repo: str
    reviewer: str
    mini_username: str
    minis_api_url: str
    trusted_service_secret: str
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
        reviewer_token=_required_env("GH_APP_SANDBOX_REVIEWER_TOKEN"),
        repo=repo,
        allowed_repo=allowed_repo,
        reviewer=_required_env("GH_APP_SANDBOX_REVIEWER"),
        mini_username=_required_env("GH_APP_SANDBOX_MINI_USERNAME"),
        minis_api_url=_required_env("GH_APP_SANDBOX_MINIS_API_URL").rstrip("/"),
        trusted_service_secret=_required_env("GH_APP_SANDBOX_TRUSTED_SERVICE_SECRET"),
        bot_login=os.environ.get("GH_APP_BOT_LOGIN", "").strip() or None,
        timeout_seconds=timeout_seconds,
        keep_pr=os.environ.get("LIVE_GH_APP_E2E_KEEP_PR", "").strip().lower()
        in {"1", "true", "yes"},
    )


def admin_action_message(error: Exception) -> str:
    return (
        f"{error}\n\n"
        "Admin action: configure repository Actions secrets/variables for the live sandbox lane:\n"
        "- GH_APP_SANDBOX_TOKEN: fine-grained token with contents/pull-requests "
        "write on the sandbox repo.\n"
        "- GH_APP_SANDBOX_REVIEWER_TOKEN: token for GH_APP_SANDBOX_REVIEWER with "
        "pull-requests write, used to submit the human outcome.\n"
        "- GH_APP_SANDBOX_REPO and GH_APP_SANDBOX_ALLOWED_REPO: the same owner/repo "
        "sandbox value.\n"
        "- GH_APP_SANDBOX_REVIEWER: a human GitHub username with an existing ready mini.\n"
        "- GH_APP_SANDBOX_MINI_USERNAME: username used for @username-mini mention tests.\n"
        "- GH_APP_SANDBOX_MINIS_API_URL and GH_APP_SANDBOX_TRUSTED_SERVICE_SECRET: "
        "trusted backend readback for mini and review-cycle diagnostics.\n"
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
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SandboxAPIError(
                "GitHub", method, path, response.status_code, response.text
            ) from exc
        if not response.content:
            return None
        return response.json()


class MinisClient:
    def __init__(self, base_url: str, trusted_service_secret: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Trusted-Service-Secret": trusted_service_secret},
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._client.request(method, path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SandboxAPIError(
                "Minis", method, path, response.status_code, response.text
            ) from exc
        if not response.content:
            return None
        return response.json()

    async def get_mini_by_username(self, username: str) -> dict[str, Any]:
        return await self.request("GET", f"/api/minis/trusted/by-username/{username}")

    async def get_review_cycle(self, mini_id: str, external_id: str) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/api/minis/trusted/{mini_id}/review-cycles",
            params={"external_id": external_id, "source_type": "github"},
        )


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
    last_observation: dict[str, Any] = {}
    while time.monotonic() < deadline:
        probe_result = await probe()
        if len(probe_result) == 2:
            result, count = probe_result
            observation = {}
        else:
            result, count, observation = probe_result
        last_count = count
        last_observation = observation or {}
        if result:
            return result
        await asyncio.sleep(interval_seconds)
    raise TimeoutError(
        "Timed out waiting for "
        f"{description}; inspected {last_count} candidate(s); "
        f"last_observation={json.dumps(last_observation, sort_keys=True, default=str)}"
    )


async def run_preflight_checks(
    client: GitHubClient,
    reviewer_client: GitHubClient,
    minis_client: MinisClient,
    cfg: SandboxConfig,
) -> dict[str, Any]:
    repo = await client.request("GET", f"/repos/{cfg.repo}")
    actor = await client.request("GET", "/user")
    reviewer_actor = await reviewer_client.request("GET", "/user")
    if reviewer_actor.get("login", "").lower() != cfg.reviewer.lower():
        raise ConfigError(
            "GH_APP_SANDBOX_REVIEWER_TOKEN does not authenticate as "
            f"GH_APP_SANDBOX_REVIEWER ({cfg.reviewer}); got {reviewer_actor.get('login')!r}."
        )

    try:
        reviewer_permission = await client.request(
            "GET",
            f"/repos/{cfg.repo}/collaborators/{cfg.reviewer}/permission",
        )
    except SandboxAPIError as exc:
        if exc.status_code == 404:
            raise ConfigError(
                f"GH_APP_SANDBOX_REVIEWER={cfg.reviewer} is not a collaborator on {cfg.repo}."
            ) from exc
        raise

    mini = await minis_client.get_mini_by_username(cfg.reviewer)
    if mini.get("status") != "ready":
        raise ConfigError(
            f"Trusted backend returned mini {mini.get('id')} for {cfg.reviewer}, "
            f"but status is {mini.get('status')!r}."
        )
    if cfg.mini_username.lower() != cfg.reviewer.lower():
        mention_mini = await minis_client.get_mini_by_username(cfg.mini_username)
        if mention_mini.get("status") != "ready":
            raise ConfigError(
                f"Trusted backend returned mini {mention_mini.get('id')} for "
                f"{cfg.mini_username}, but status is {mention_mini.get('status')!r}."
            )

    return {
        "repo": {
            "full_name": repo.get("full_name"),
            "default_branch": repo.get("default_branch"),
            "archived": repo.get("archived"),
        },
        "actor_login": actor.get("login"),
        "reviewer_login": reviewer_actor.get("login"),
        "reviewer_permission": reviewer_permission.get("permission")
        or reviewer_permission.get("role_name"),
        "mini_id": mini.get("id"),
        "mini_status": mini.get("status"),
    }


async def create_sandbox_pr(
    client: GitHubClient,
    cfg: SandboxConfig,
    run_id: str,
) -> dict[str, Any]:
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
    except SandboxAPIError as exc:
        if exc.status_code in {403, 422}:
            raise RuntimeError(
                "Failed to request the sandbox reviewer. Admin action: ensure "
                "GH_APP_SANDBOX_REVIEWER is a collaborator who can be requested on "
                f"{cfg.repo} and has a ready mini named {cfg.reviewer}."
            ) from exc
        raise


async def wait_for_requested_review(
    client: GitHubClient, cfg: SandboxConfig, pr_number: int
) -> dict[str, Any]:
    async def probe() -> tuple[dict[str, Any] | None, int, dict[str, Any]]:
        reviews = await client.request("GET", f"/repos/{cfg.repo}/pulls/{pr_number}/reviews")
        for review in reviews:
            body = review.get("body") or ""
            if _is_expected_bot(review, cfg.bot_login) and _has_mini_signature(body, cfg.reviewer):
                return review, len(reviews), {}
        return None, len(reviews), {
            "review_users": [
                {
                    "id": review.get("id"),
                    "state": review.get("state"),
                    "user": (review.get("user") or {}).get("login"),
                    "type": (review.get("user") or {}).get("type"),
                    "has_body": bool(review.get("body")),
                }
                for review in reviews[-5:]
            ]
        }

    return await _poll_until(
        timeout_seconds=cfg.timeout_seconds,
        interval_seconds=10,
        probe=probe,
        description="requested-reviewer Minis PR review",
    )


async def post_mention_comment(
    client: GitHubClient,
    cfg: SandboxConfig,
    pr_number: int,
) -> dict[str, Any]:
    return await client.request(
        "POST",
        f"/repos/{cfg.repo}/issues/{pr_number}/comments",
        json={
            "body": (
                f"@{cfg.mini_username}-mini what do you think about this change for "
                "the live GitHub App sandbox e2e?"
            )
        },
    )


async def wait_for_mention_response(
    client: GitHubClient,
    cfg: SandboxConfig,
    pr_number: int,
    mention_comment_id: int,
) -> dict[str, Any]:
    async def probe() -> tuple[dict[str, Any] | None, int, dict[str, Any]]:
        comments = await client.request("GET", f"/repos/{cfg.repo}/issues/{pr_number}/comments")
        candidates = [comment for comment in comments if comment.get("id", 0) > mention_comment_id]
        for comment in candidates:
            body = comment.get("body") or ""
            if _is_expected_bot(comment, cfg.bot_login) and _has_mini_signature(
                body, cfg.mini_username
            ):
                return comment, len(candidates), {}
        return None, len(candidates), {
            "candidate_comments": [
                {
                    "id": comment.get("id"),
                    "user": (comment.get("user") or {}).get("login"),
                    "type": (comment.get("user") or {}).get("type"),
                    "has_mini_signature": BOT_SIGNATURE in (comment.get("body") or ""),
                }
                for comment in candidates[-5:]
            ]
        }

    return await _poll_until(
        timeout_seconds=cfg.timeout_seconds,
        interval_seconds=10,
        probe=probe,
        description="@mini mention response",
    )


async def post_human_review_outcome(
    client: GitHubClient,
    cfg: SandboxConfig,
    pr_number: int,
) -> dict[str, Any]:
    return await client.request(
        "POST",
        f"/repos/{cfg.repo}/pulls/{pr_number}/reviews",
        json={
            "event": "COMMENT",
            "body": (
                "- **Note** `sandbox-outcome`: Live sandbox reviewer outcome captured. "
                "Why: verifies GitHub App review-cycle writeback."
            ),
        },
    )


def _review_cycle_external_id(cfg: SandboxConfig, pr_number: int) -> str:
    return f"{cfg.repo}#{pr_number}:{cfg.reviewer.lower()}"


async def wait_for_outcome_capture(
    minis_client: MinisClient,
    cfg: SandboxConfig,
    mini_id: str,
    pr_number: int,
    review_id: int,
) -> dict[str, Any]:
    external_id = _review_cycle_external_id(cfg, pr_number)

    async def probe() -> tuple[dict[str, Any] | None, int, dict[str, Any]]:
        try:
            cycle = await minis_client.get_review_cycle(mini_id, external_id)
        except SandboxAPIError as exc:
            if exc.status_code == 404:
                return None, 0, {"cycle_found": False, "external_id": external_id}
            raise

        human_outcome = cycle.get("human_review_outcome")
        delta_metrics = cycle.get("delta_metrics") or {}
        if human_outcome and delta_metrics.get("github_review_id") == review_id:
            return cycle, 1, {}
        return None, 1, {
            "cycle_found": True,
            "external_id": external_id,
            "human_reviewed_at": cycle.get("human_reviewed_at"),
            "delta_metrics": delta_metrics,
            "has_human_review_outcome": bool(human_outcome),
        }

    return await _poll_until(
        timeout_seconds=cfg.timeout_seconds,
        interval_seconds=10,
        probe=probe,
        description="trusted backend review-cycle outcome capture",
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
    reviewer_client = GitHubClient(cfg.reviewer_token)
    minis_client = MinisClient(cfg.minis_api_url, cfg.trusted_service_secret)
    pr: dict[str, Any] | None = None
    try:
        preflight = await run_preflight_checks(client, reviewer_client, minis_client, cfg)
        pr = await create_sandbox_pr(client, cfg, run_id)
        await request_reviewer(client, cfg, pr["number"])
        requested_review = await wait_for_requested_review(client, cfg, pr["number"])
        human_review = await post_human_review_outcome(reviewer_client, cfg, pr["number"])
        captured_cycle = await wait_for_outcome_capture(
            minis_client,
            cfg,
            str(preflight["mini_id"]),
            pr["number"],
            human_review["id"],
        )
        mention = await post_mention_comment(client, cfg, pr["number"])
        mention_response = await wait_for_mention_response(client, cfg, pr["number"], mention["id"])
        return {
            "repo": cfg.repo,
            "pr_number": pr["number"],
            "pr_url": pr["html_url"],
            "preflight": preflight,
            "requested_review_id": requested_review.get("id"),
            "human_review_id": human_review.get("id"),
            "captured_review_cycle_id": captured_cycle.get("id"),
            "captured_review_cycle_external_id": captured_cycle.get("external_id"),
            "mention_comment_id": mention_response.get("id"),
            "kept_pr": cfg.keep_pr,
        }
    finally:
        if pr is not None and not cfg.keep_pr:
            await cleanup_pr(client, cfg, pr)
        await minis_client.close()
        await reviewer_client.close()
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
        client = GitHubClient(cfg.token)
        reviewer_client = GitHubClient(cfg.reviewer_token)
        minis_client = MinisClient(cfg.minis_api_url, cfg.trusted_service_secret)
        try:
            preflight = await run_preflight_checks(client, reviewer_client, minis_client, cfg)
        except Exception as exc:
            print(f"::error::{admin_action_message(exc)}")
            return 2
        finally:
            await minis_client.close()
            await reviewer_client.close()
            await client.close()
        print(json.dumps({"status": "preflight_ok", **preflight}, indent=2, sort_keys=True))
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
