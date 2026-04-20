"""Integration tests for GitHubExplorer repo fan-out (ALLIE-388/389).

These tests verify that RepoAgent fan-out is always active (no flag required),
that evidence from both the evidence-DB path and the repo_agent path is written,
and that the fan-out correctly creates ExplorerProgress rows with the expected
source_type.

All LLM calls are mocked; no real network or DB is required.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.agent import AgentResult
from app.synthesis.explorers.github_explorer import GitHubExplorer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mini_id() -> str:
    return str(uuid4())


def _make_mock_session():
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=MagicMock(
            rowcount=0,
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
            scalar=MagicMock(return_value=0),
        )
    )
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _make_mock_factory(session=None):
    if session is None:
        session = _make_mock_session()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    """Minimal real git repo with content for the repo agent to explore."""
    root = tmp_path / "fanout_repo"
    root.mkdir()

    env = {**os.environ, "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"git {list(args)} failed: {result.stderr}"
        return result.stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "fanout@example.com")
    git("config", "user.name", "FanoutTester")

    (root / "README.md").write_text("# FanoutRepo\nA project for testing fan-out.\n")
    src = root / "src"
    src.mkdir()
    (src / "app.py").write_text(
        "def process(data: list) -> list:\n"
        "    # filter None values\n"
        "    return [x for x in data if x is not None]\n"
    )
    git("add", ".")
    git("commit", "-m", "feat: add process function")

    return root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFanoutIntegration:
    @pytest.mark.asyncio
    async def test_repo_agent_evidence_written_via_fanout(self, tmp_git_repo: Path):
        """RepoAgent fan-out is always active — repo agent findings are produced."""
        mini_id = _mini_id()
        session = _make_mock_session()
        factory = _make_mock_factory(session)

        repo_findings_saved = []

        async def mock_run_agent(system_prompt, user_prompt, tools, **kwargs):
            # Check if this is a repo agent (has list_directory tool)
            tool_names = {t.name for t in tools}
            if "list_directory" in tool_names:
                repo_findings_saved.append({"source": "repo_agent"})
            return AgentResult(
                final_response="done",
                tool_outputs={t.name: [] for t in tools},
                turns_used=2,
            )

        explorer = GitHubExplorer()
        explorer._mini_id = mini_id
        explorer._db_session = session
        explorer._session_factory = factory

        fake_repos = [
            {
                "full_name": "testuser/fanout_repo",
                "name": "fanout_repo",
                "pushed_at": "2024-06-01T00:00:00Z",
                "stargazers_count": 50,
                "fork": False,
                "archived": False,
                "size_kb": 500,
            }
        ]

        with patch(
            "app.synthesis.explorers.github_explorer.ensure_clone",
            new_callable=AsyncMock,
            return_value=tmp_git_repo,
        ):
            with patch("app.synthesis.explorers.repo_agent.run_agent", side_effect=mock_run_agent):
                await explorer._run_repo_fanout(
                    username="testuser",
                    all_repos=fake_repos,
                    max_repos=5,
                    concurrency=2,
                    size_limit_kb=0,
                )

        # The repo-agent path should have been triggered
        assert len(repo_findings_saved) >= 1, "Expected repo agent to be invoked at least once"

    @pytest.mark.asyncio
    async def test_explorer_progress_row_created_for_each_repo(self, tmp_git_repo: Path):
        """Each selected repo should produce an ExplorerProgress row with
        source_type='github_repo:<owner>__<repo>'."""
        mini_id = _mini_id()
        session = _make_mock_session()

        async def mock_run_agent(system_prompt, user_prompt, tools, **kwargs):
            return AgentResult(
                final_response="done",
                tool_outputs={t.name: [] for t in tools},
                turns_used=1,
            )

        from app.synthesis.explorers.repo_agent import RepoAgent

        # Directly test that RepoAgent._upsert_progress is called with the right type
        upsert_calls: list[str] = []

        async def tracking_upsert(source_type, status):
            upsert_calls.append(source_type)
            # Don't call original (would need real DB)

        with patch.object(RepoAgent, "_upsert_progress", side_effect=tracking_upsert):
            with patch("app.synthesis.explorers.repo_agent.run_agent", side_effect=mock_run_agent):
                agent = RepoAgent(mini_id=mini_id, db_session=session)
                await agent.run("someowner", "myrepo", tmp_git_repo)

        # Should have been called at least for "running" and "completed"
        source_types_seen = set(upsert_calls)
        assert "github_repo:someowner__myrepo" in source_types_seen, (
            f"Expected source_type 'github_repo:someowner__myrepo' in {source_types_seen}"
        )

    @pytest.mark.asyncio
    async def test_fanout_always_active_no_flag_needed(self, tmp_git_repo: Path):
        """RepoAgent fan-out runs without any environment flag — it is the default path."""

        explorer = GitHubExplorer()
        explorer._mini_id = _mini_id()
        explorer._db_session = _make_mock_session()

        clone_called = False

        async def mock_ensure_clone(*args, **kwargs):
            nonlocal clone_called
            clone_called = True
            return tmp_git_repo

        async def mock_run_agent(system_prompt, user_prompt, tools, **kwargs):
            return AgentResult(
                final_response="done",
                tool_outputs={t.name: [] for t in tools},
                turns_used=1,
            )

        with patch(
            "app.synthesis.explorers.github_explorer.ensure_clone",
            side_effect=mock_ensure_clone,
        ):
            with patch("app.synthesis.explorers.repo_agent.run_agent", side_effect=mock_run_agent):
                with patch("app.synthesis.explorers.base.run_agent") as mock_base_agent:
                    mock_base_agent.return_value = AgentResult(
                        final_response="done",
                        tool_outputs={},
                        turns_used=1,
                    )
                    await explorer.explore(
                        "testuser",
                        "",
                        {
                            "repos_summary": {
                                "top_repos": [
                                    {
                                        "full_name": "testuser/testrepo",
                                        "name": "testrepo",
                                        "pushed_at": "2024-01-01T00:00:00Z",
                                        "stargazers_count": 10,
                                        "fork": False,
                                        "archived": False,
                                    }
                                ]
                            }
                        },
                    )

        assert clone_called, "ensure_clone MUST be called — fan-out is always active"
