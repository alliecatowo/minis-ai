from __future__ import annotations

import json
import subprocess
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

import cli as minis_cli


runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_auth_env(monkeypatch, tmp_path):
    monkeypatch.delenv("MINIS_TOKEN", raising=False)
    monkeypatch.delenv("MINIS_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("MINIS_AUTH_TOKEN_FILE", str(tmp_path / "missing-token"))


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


class _FakeStream:
    def __init__(self, lines: list[str], *, status_code: int = 200):
        self._lines = lines
        self._response = httpx.Response(
            status_code,
            request=httpx.Request("POST", "https://api.test/api/minis/mini-1/chat"),
            text="error",
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self) -> None:
        self._response.raise_for_status()

    def iter_lines(self):
        yield from self._lines


def test_create_requires_auth_before_calling_api(monkeypatch):
    def unexpected_post(*args, **kwargs):
        raise AssertionError("API should not be called without auth")

    monkeypatch.setattr(minis_cli.httpx, "post", unexpected_post)

    result = runner.invoke(minis_cli.app, ["create", "octocat"])

    assert result.exit_code == 1
    assert "Authentication required" in result.output
    assert "MINIS_TOKEN" in result.output


def test_auth_headers_read_mcp_token_file(monkeypatch, tmp_path):
    token_file = tmp_path / "mcp-token"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.delenv("MINIS_TOKEN", raising=False)
    monkeypatch.delenv("MINIS_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("MINIS_AUTH_TOKEN_FILE", str(token_file))

    assert minis_cli._auth_headers()["Authorization"] == "Bearer file-token"


def test_env_token_takes_precedence_over_mcp_token_file(monkeypatch, tmp_path):
    token_file = tmp_path / "mcp-token"
    token_file.write_text("file-token\n", encoding="utf-8")
    monkeypatch.setenv("MINIS_TOKEN", "env-token")
    monkeypatch.setenv("MINIS_AUTH_TOKEN_FILE", str(token_file))

    assert minis_cli._auth_headers()["Authorization"] == "Bearer env-token"


def test_list_happy_path_uses_hosted_api(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")
    captured: dict[str, Any] = {}

    def fake_get(url: str, **kwargs) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return _response(
            "GET",
            url,
            json={
                "data": [
                    {
                        "id": "mini-1",
                        "username": "octocat",
                        "display_name": "Octo Cat",
                        "status": "ready",
                        "created_at": "2026-04-25T12:00:00Z",
                    }
                ],
                "next_cursor": None,
                "has_more": False,
            },
        )

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)

    result = runner.invoke(minis_cli.app, ["list"])

    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://api.test/api/minis?mine=false"
    assert captured["headers"] == {"Accept": "application/json"}
    assert "octocat" in result.output
    assert "ready" in result.output


def test_list_json_prints_raw_hosted_payload(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")

    def fake_get(url: str, **kwargs) -> httpx.Response:
        return _response(
            "GET",
            url,
            json={
                "data": [{"id": "mini-1", "username": "octocat", "status": "ready"}],
                "next_cursor": None,
                "has_more": False,
            },
        )

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)

    result = runner.invoke(minis_cli.app, ["list", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["data"][0]["username"] == "octocat"
    assert "Minis" not in result.output


def test_create_happy_path_sends_bearer_token(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")
    monkeypatch.setenv("MINIS_TOKEN", "secret-token")
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["json"] = kwargs.get("json")
        return _response(
            "POST",
            url,
            status_code=202,
            json={"id": "mini-1", "username": "octocat", "status": "processing"},
        )

    monkeypatch.setattr(minis_cli.httpx, "post", fake_post)

    result = runner.invoke(minis_cli.app, ["create", "octocat"])

    assert result.exit_code == 0, result.output
    assert captured["url"] == "https://api.test/api/minis"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["json"] == {"username": "octocat", "sources": ["github"]}
    assert "create accepted" in result.output
    assert "processing" in result.output


def test_create_json_prints_raw_create_payload(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")
    monkeypatch.setenv("MINIS_TOKEN", "secret-token")

    def fake_post(url: str, **kwargs) -> httpx.Response:
        return _response(
            "POST",
            url,
            status_code=202,
            json={"id": "mini-1", "username": "octocat", "status": "processing"},
        )

    monkeypatch.setattr(minis_cli.httpx, "post", fake_post)

    result = runner.invoke(minis_cli.app, ["create", "octocat", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "processing"
    assert "create accepted" not in result.output


def test_status_shows_api_and_auth_state(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")
    monkeypatch.setenv("MINIS_TOKEN", "secret-token")

    def fake_get(url: str, **kwargs) -> httpx.Response:
        if url.endswith("/api/health"):
            return _response("GET", url, json={"status": "ok"})
        if url.endswith("/api/auth/me"):
            return _response(
                "GET",
                url,
                json={
                    "id": "user-1",
                    "github_username": "octocat",
                    "display_name": "Octo Cat",
                    "avatar_url": None,
                },
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)

    result = runner.invoke(minis_cli.app, ["status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["api"] == "ok"
    assert payload["auth"] == "authenticated"
    assert payload["token_source"] == "MINIS_TOKEN"
    assert payload["user"]["github_username"] == "octocat"


def test_status_json_stays_clean_when_token_is_invalid(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")
    monkeypatch.setenv("MINIS_TOKEN", "bad-token")

    def fake_get(url: str, **kwargs) -> httpx.Response:
        if url.endswith("/api/health"):
            return _response("GET", url, json={"status": "ok"})
        if url.endswith("/api/auth/me"):
            return _response("GET", url, status_code=401, json={"detail": "Unauthorized"})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)

    result = runner.invoke(minis_cli.app, ["status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["api"] == "ok"
    assert payload["auth"] == "invalid"
    assert payload["user"] is None


def test_login_guides_to_mcp_device_auth_without_api_call(monkeypatch):
    def unexpected_get(*args, **kwargs):
        raise AssertionError("login guidance should not call the API without a token")

    monkeypatch.setattr(minis_cli.httpx, "get", unexpected_get)

    result = runner.invoke(minis_cli.app, ["login"])

    assert result.exit_code == 0
    assert "shared with the Minis MCP server" in result.output
    assert "uv run minis-mcp auth login" in result.output


def test_chat_one_shot_collects_sse_chunks(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")
    captured: dict[str, Any] = {}

    def fake_get(url: str, **kwargs) -> httpx.Response:
        return _response(
            "GET",
            url,
            json={
                "id": "mini-1",
                "username": "octocat",
                "display_name": "Octo Cat",
                "status": "ready",
            },
        )

    def fake_stream(method: str, url: str, **kwargs) -> _FakeStream:
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeStream(
            [
                "event: conversation_id",
                "data: conv-1",
                "",
                "event: chunk",
                "data: Hello ",
                "",
                "event: chunk",
                "data: world",
                "",
                "event: done",
                "data: ",
                "",
            ]
        )

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)
    monkeypatch.setattr(minis_cli.httpx, "stream", fake_stream)

    result = runner.invoke(minis_cli.app, ["chat", "octocat", "What do you think?"])

    assert result.exit_code == 0, result.output
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.test/api/minis/mini-1/chat"
    assert captured["json"]["message"] == "What do you think?"
    assert captured["json"]["history"] == []
    assert "Hello world" in result.output


def test_chat_returns_explicit_gated_state_when_mini_processing(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")

    def fake_get(url: str, **kwargs) -> httpx.Response:
        return _response(
            "GET",
            url,
            json={"id": "mini-1", "username": "octocat", "status": "processing"},
        )

    def unexpected_stream(*args, **kwargs):
        raise AssertionError("chat stream should not be opened when mini is gated")

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)
    monkeypatch.setattr(minis_cli.httpx, "stream", unexpected_stream)

    result = runner.invoke(minis_cli.app, ["chat", "octocat", "hi"])

    assert result.exit_code == 1
    assert "Chat unavailable" in result.output
    assert "gated until" in result.output
    assert "status=ready" in result.output


def test_chat_error_event_is_not_rendered_as_fake_output(monkeypatch):
    monkeypatch.setenv("MINIS_API_BASE", "https://api.test/api")

    def fake_get(url: str, **kwargs) -> httpx.Response:
        return _response(
            "GET",
            url,
            json={"id": "mini-1", "username": "octocat", "status": "ready"},
        )

    def fake_stream(method: str, url: str, **kwargs) -> _FakeStream:
        return _FakeStream(
            [
                "event: error",
                "data: DISABLE_LLM_CALLS is enabled",
                "",
            ]
        )

    monkeypatch.setattr(minis_cli.httpx, "get", fake_get)
    monkeypatch.setattr(minis_cli.httpx, "stream", fake_stream)

    result = runner.invoke(minis_cli.app, ["chat", "octocat", "hi"])

    assert result.exit_code == 1
    assert "Chat unavailable" in result.output
    assert "DISABLE_LLM_CALLS is enabled" in result.output
    assert "octocat:" in result.output


def test_ingest_run_wrapper_invokes_local_regen_script(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        captured["env"] = kwargs.get("env")
        captured["check"] = kwargs.get("check")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(minis_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        minis_cli.app,
        [
            "ingest",
            "run",
            "octocat",
            "--mode",
            "full",
            "--sources",
            "github",
            "--run-id",
            "run-123",
            "--timeout",
            "30",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["cmd"] == [
        "uv",
        "run",
        "python",
        "scripts/regen_mini.py",
        "octocat",
        "--mode",
        "full",
        "--sources",
        "github",
        "--freshness-mode",
        "replace",
        "--run-id",
        "run-123",
        "--timeout",
        "30",
        "--json",
    ]
    assert captured["cwd"] == minis_cli._backend_dir
    assert captured["check"] is True
    assert captured["env"]["PYTHONUNBUFFERED"] == "1"
    assert captured["env"]["PYTHONPATH"] == "."


def test_ingest_status_wrapper_invokes_local_status_script(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_run(cmd: list[str], **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(minis_cli.subprocess, "run", fake_run)

    result = runner.invoke(
        minis_cli.app,
        [
            "ingest",
            "status",
            "octocat",
            "--watch",
            "--interval",
            "3",
            "--run-id",
            "run-123",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["cmd"] == [
        "uv",
        "run",
        "python",
        "scripts/ingest_status.py",
        "octocat",
        "--watch",
        "--interval",
        "3",
        "--run-id",
        "run-123",
        "--json",
    ]


def test_ingest_wrapper_propagates_script_exit_code(monkeypatch):
    def failing_run(cmd: list[str], **kwargs):
        raise subprocess.CalledProcessError(returncode=2, cmd=cmd)

    monkeypatch.setattr(minis_cli.subprocess, "run", failing_run)

    result = runner.invoke(minis_cli.app, ["ingest", "resume", "octocat"])

    assert result.exit_code == 2
