"""Tests for recorded upstream contract fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.ingestion.github import fetch_user_repos_graphql
from tests.support.upstream_contracts import (
    REDACTED,
    UpstreamFixtureConfig,
    UpstreamFixtureError,
    UpstreamFixtureMode,
    UpstreamFixtureTransport,
    mode_from_env,
    redact_value,
    require_live_upstream,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "upstream" / "github"


@pytest.mark.asyncio
async def test_replays_github_graphql_contract_fixture_deterministically():
    """A GitHub-shaped GraphQL fixture can drive the real response mapper offline."""
    transport = UpstreamFixtureTransport(
        UpstreamFixtureConfig(
            path=FIXTURE_DIR / "repos_graphql_success.json",
            mode=UpstreamFixtureMode.REPLAY,
            provider="github",
        )
    )

    async with httpx.AsyncClient(transport=transport) as client:
        result = await fetch_user_repos_graphql(client, "contract-user", top_n=1)

    transport.assert_all_consumed()

    assert result is not None
    repos, repo_langs = result
    assert repos == [
        {
            "name": "decision-frameworks",
            "full_name": "contract-user/decision-frameworks",
            "description": "Recorded fixture for upstream contract tests",
            "language": "Python",
            "stargazers_count": 7,
            "topics": ["testing", "contracts"],
            "pushed_at": "2026-04-20T12:34:56Z",
            "fork": False,
            "archived": False,
        }
    ]
    assert repo_langs == {"contract-user/decision-frameworks": {"Python": 1200, "Shell": 80}}


@pytest.mark.asyncio
async def test_replay_rejects_unexpected_request_order():
    transport = UpstreamFixtureTransport(
        UpstreamFixtureConfig(
            path=FIXTURE_DIR / "repos_graphql_success.json",
            mode=UpstreamFixtureMode.REPLAY,
        )
    )

    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(UpstreamFixtureError, match="upstream request mismatch"):
            await client.get("https://api.github.com/users/contract-user")


def test_redacts_nested_secret_fields_and_env_values(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_secret")

    redacted = redact_value(
        {
            "token": "plain-token",
            "metadata": {
                "url": "https://example.test?access_token=github_pat_secret",
                "safe": "kept",
            },
        }
    )

    assert redacted["token"] == REDACTED
    assert redacted["metadata"]["url"] == f"https://example.test?access_token={REDACTED}"
    assert redacted["metadata"]["safe"] == "kept"


def test_record_mode_writes_redacted_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tests.support import upstream_contracts

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    fixture_path = tmp_path / "recording.json"

    upstream_contracts._write_fixture(
        fixture_path,
        {
            "version": 1,
            "provider": "github",
            "interactions": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://api.github.com/user",
                        "headers": {"authorization": "Bearer ghp_secret"},
                        "body": None,
                    },
                    "response": {
                        "status_code": 200,
                        "headers": {},
                        "body": json.dumps({"login": "contract-user"}),
                    },
                }
            ],
        },
    )

    serialized = fixture_path.read_text()
    assert "ghp_secret" not in serialized
    assert REDACTED in serialized


def test_live_mode_skips_without_explicit_gate(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("UPSTREAM_CONTRACT_LIVE", raising=False)

    with pytest.raises(pytest.skip.Exception):
        require_live_upstream(
            UpstreamFixtureConfig(
                path=Path("unused.json"),
                mode=UpstreamFixtureMode.RECORD,
                required_env=("GITHUB_TOKEN",),
            )
        )


def test_mode_from_env_defaults_to_replay(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("UPSTREAM_CONTRACT_MODE", raising=False)

    assert mode_from_env() == UpstreamFixtureMode.REPLAY
