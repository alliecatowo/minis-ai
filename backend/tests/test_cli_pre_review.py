from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
from typer.testing import CliRunner

import cli as minis_cli


runner = CliRunner()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo,
    )
    return completed.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "branch", "-M", "main")
    (repo / "tracked.txt").write_text("hello\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    return repo


def _response(
    method: str,
    url: str,
    *,
    status_code: int = 200,
    json: object | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        request=httpx.Request(method, url),
        json=json,
    )


def test_pre_review_collects_git_context_and_prints_blockers(monkeypatch, tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "tracked.txt").write_text("hello\nmore context\n")
    (repo / "new_file.py").write_text("print('hi')\n")

    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs) -> httpx.Response:
        assert url.endswith("/api/minis/by-username/reviewer")
        captured["get_headers"] = kwargs.get("headers")
        return _response(
            "GET",
            url,
            json={"id": "mini-123", "username": "reviewer", "status": "ready"},
        )

    def fake_post(url: str, **kwargs) -> httpx.Response:
        captured["post_url"] = url
        captured["payload"] = kwargs["json"]
        return _response(
            "POST",
            url,
            json={
                "version": "review_prediction_v1",
                "reviewer_username": "reviewer",
                "repo_name": "tmp/repo",
                "private_assessment": {
                    "blocking_issues": [
                        {
                            "key": "test-coverage",
                            "summary": "Add coverage around the new code path before review.",
                            "confidence": 0.92,
                        }
                    ],
                    "non_blocking_issues": [],
                    "open_questions": [
                        {"summary": "What is the rollback path if the behavior changes?"}
                    ],
                    "positive_signals": [],
                    "confidence": 0.8,
                },
                "delivery_policy": {
                    "author_model": "senior_peer",
                    "context": "normal",
                    "strictness": "high",
                    "teaching_mode": False,
                    "shield_author_from_noise": False,
                    "rationale": "High-signal review.",
                },
                "expressed_feedback": {
                    "summary": "Likely requests changes until tests land.",
                    "comments": [],
                    "approval_state": "request_changes",
                },
            },
        )

    monkeypatch.chdir(repo)
    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)
    monkeypatch.setattr(minis_cli.httpx, "post", fake_post)

    result = runner.invoke(
        minis_cli.app,
        [
            "pre-review",
            "reviewer",
            "--base",
            "HEAD",
            "--title",
            "Refactor auth flow",
            "--author-model",
            "senior_peer",
        ],
    )

    assert result.exit_code == 0
    assert "Likely blockers" in result.output
    assert "test-coverage" in result.output
    assert "rollback path" in result.output
    assert captured["post_url"].endswith("/api/minis/mini-123/review-prediction")

    payload = captured["payload"]
    assert payload["title"] == "Refactor auth flow"
    assert payload["author_model"] == "senior_peer"
    assert payload["delivery_context"] == "normal"
    assert payload["repo_name"] == repo.name
    assert set(payload["changed_files"]) == {"new_file.py", "tracked.txt"}
    assert payload["diff_summary"]


def test_pre_review_fails_fast_when_there_are_no_changes(monkeypatch, tmp_path):
    repo = _init_repo(tmp_path)

    def unexpected_get(*args, **kwargs):
        raise AssertionError("API should not be called when there is no git diff")

    monkeypatch.chdir(repo)
    monkeypatch.setattr(minis_cli.httpx, "get", unexpected_get)

    result = runner.invoke(
        minis_cli.app,
        ["pre-review", "reviewer", "--base", "HEAD"],
    )

    assert result.exit_code == 1
    assert "No local changes found for pre-review" in result.output
