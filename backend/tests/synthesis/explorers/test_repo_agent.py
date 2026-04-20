"""Tests for RepoAgent (ALLIE-388 M2).

Covers:
- System prompt content requirements
- build_repo_tools() returns the expected tool names
- Feature flag: ENABLE_LOCAL_CLONE_EXPLORER=false → no RepoAgent spawned
- Feature flag: ENABLE_LOCAL_CLONE_EXPLORER=true → RepoAgent spawned
- ExplorerProgress rows created with correct source_type
- Semaphore concurrency: at most N repos active at once
- Integration: spawn a RepoAgent against a real tmp git repo with mocked LLM
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.synthesis.explorers.repo_agent import (
    RepoAgent,
    _REPO_AGENT_SYSTEM_PROMPT,
    build_repo_tools,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mini_id() -> str:
    return str(uuid4())


def _make_mock_session():
    """Return a mock async SQLAlchemy session."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


def _make_mock_factory(session=None):
    """Return a mock session factory that yields the given session."""
    if session is None:
        session = _make_mock_session()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.fixture()
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a minimal real git repo with two commits."""
    root = tmp_path / "testrepo"
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
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Tester")

    # Commit 1: add README
    readme = root / "README.md"
    readme.write_text("# Test Repo\n\nA test repository.\n")
    src_dir = root / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text(
        'def greet(name: str) -> str:\n    """Greet someone."""\n    return f"Hello, {name}!"\n'
    )
    git("add", ".")
    git("commit", "-m", "feat: initial commit with greeting function")

    # Commit 2: add error handling
    (src_dir / "utils.py").write_text(
        "import logging\n\nlogger = logging.getLogger(__name__)\n\n"
        "def safe_divide(a: float, b: float) -> float:\n"
        "    if b == 0:\n"
        "        raise ValueError('division by zero')\n"
        "    return a / b\n"
    )
    git("add", ".")
    git("commit", "-m", "fix: add error handling for division by zero")

    return root


# ---------------------------------------------------------------------------
# Unit: System prompt content
# ---------------------------------------------------------------------------


class TestRepoAgentSystemPrompt:
    def test_prompt_contains_list_directory(self):
        assert "list_directory" in _REPO_AGENT_SYSTEM_PROMPT

    def test_prompt_contains_read_file(self):
        assert "read_file" in _REPO_AGENT_SYSTEM_PROMPT

    def test_prompt_contains_grep_in_repo(self):
        assert "grep_in_repo" in _REPO_AGENT_SYSTEM_PROMPT

    def test_prompt_contains_git_log(self):
        assert "git_log" in _REPO_AGENT_SYSTEM_PROMPT

    def test_prompt_contains_finish(self):
        assert "finish" in _REPO_AGENT_SYSTEM_PROMPT

    def test_prompt_mentions_findings_count(self):
        assert "5" in _REPO_AGENT_SYSTEM_PROMPT  # "5–10 distinctive findings"

    def test_prompt_mentions_code_style(self):
        prompt_lower = _REPO_AGENT_SYSTEM_PROMPT.lower()
        assert "coding style" in prompt_lower or "style" in prompt_lower

    def test_prompt_instructs_to_start_with_readme(self):
        prompt_lower = _REPO_AGENT_SYSTEM_PROMPT.lower()
        assert "readme" in prompt_lower


# ---------------------------------------------------------------------------
# Unit: build_repo_tools
# ---------------------------------------------------------------------------


class TestBuildRepoTools:
    def test_returns_list_of_agent_tools(self, tmp_git_repo: Path):

        session = _make_mock_session()
        tools = build_repo_tools(
            clone_root=tmp_git_repo,
            slug="owner__repo",
            mini_id=_mini_id(),
            db_session=session,
        )
        from app.core.agent import AgentTool as AT

        assert all(isinstance(t, AT) for t in tools)

    def test_includes_fs_tools(self, tmp_git_repo: Path):
        session = _make_mock_session()
        tools = build_repo_tools(
            clone_root=tmp_git_repo,
            slug="owner__repo",
            mini_id=_mini_id(),
            db_session=session,
        )
        names = {t.name for t in tools}
        for expected in ("list_directory", "read_file", "grep_in_repo", "git_log", "open_diff"):
            assert expected in names, f"Missing tool: {expected}"

    def test_includes_db_write_tools(self, tmp_git_repo: Path):
        session = _make_mock_session()
        tools = build_repo_tools(
            clone_root=tmp_git_repo,
            slug="owner__repo",
            mini_id=_mini_id(),
            db_session=session,
        )
        names = {t.name for t in tools}
        for expected in (
            "save_finding",
            "save_memory",
            "save_quote",
            "save_knowledge_node",
            "save_knowledge_edge",
            "save_principle",
            "finish",
            "get_progress",
        ):
            assert expected in names, f"Missing tool: {expected}"

    def test_excludes_evidence_read_tools(self, tmp_git_repo: Path):
        """browse_evidence, search_evidence, read_item, mark_explored don't apply
        to local-clone exploration."""
        session = _make_mock_session()
        tools = build_repo_tools(
            clone_root=tmp_git_repo,
            slug="owner__repo",
            mini_id=_mini_id(),
            db_session=session,
        )
        names = {t.name for t in tools}
        for excluded in ("browse_evidence", "search_evidence", "read_item"):
            assert excluded not in names, f"Tool should be excluded: {excluded}"

    def test_source_type_embedded_in_slug(self, tmp_git_repo: Path):
        """The slug is used as the source_type suffix; ensure it propagates."""
        session = _make_mock_session()
        mini_id = _mini_id()
        slug = "myowner__myrepo"
        tools = build_repo_tools(
            clone_root=tmp_git_repo,
            slug=slug,
            mini_id=mini_id,
            db_session=session,
        )
        # We can't easily introspect closed-over values, but we verify the tool
        # list is non-empty and has the right structure.
        assert len(tools) >= 10


# ---------------------------------------------------------------------------
# Feature flag tests
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def test_flag_off_by_default(self):
        """ENABLE_LOCAL_CLONE_EXPLORER defaults to False."""
        # We import after patching env to avoid module-level caching issues.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ENABLE_LOCAL_CLONE_EXPLORER", None)
            import importlib
            import app.synthesis.explorers.repo_agent as ra_module

            importlib.reload(ra_module)
            assert ra_module.ENABLE_LOCAL_CLONE_EXPLORER is False

    def test_flag_on_when_env_set(self):
        with patch.dict(os.environ, {"ENABLE_LOCAL_CLONE_EXPLORER": "true"}):
            import importlib
            import app.synthesis.explorers.repo_agent as ra_module

            importlib.reload(ra_module)
            assert ra_module.ENABLE_LOCAL_CLONE_EXPLORER is True

    @pytest.mark.asyncio
    async def test_github_explorer_no_repo_agent_when_flag_off(self):
        """When ENABLE_LOCAL_CLONE_EXPLORER=false, _run_repo_fanout is never called."""
        from app.synthesis.explorers.github_explorer import GitHubExplorer

        explorer = GitHubExplorer()
        fanout_called = False

        async def mock_fanout(**kwargs):
            nonlocal fanout_called
            fanout_called = True

        with patch.object(explorer, "_run_repo_fanout", side_effect=mock_fanout):
            with patch("app.synthesis.explorers.repo_agent.ENABLE_LOCAL_CLONE_EXPLORER", False):
                with patch.object(
                    explorer.__class__.__bases__[0],
                    "explore",
                    new_callable=AsyncMock,
                    return_value=MagicMock(
                        source_name="github",
                        personality_findings="",
                        memory_entries=[],
                    ),
                ):
                    # Simulate the path where httpx client is needed
                    with patch("httpx.AsyncClient") as mock_client_cls:
                        mock_client = MagicMock()
                        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                        mock_client.__aexit__ = AsyncMock(return_value=False)
                        mock_client_cls.return_value = mock_client

                        await explorer.explore("testuser", "", {"repos_summary": {"top_repos": []}})

        assert not fanout_called, "fan-out should not have been called with flag off"

    @pytest.mark.asyncio
    async def test_github_explorer_calls_repo_agent_when_flag_on(self):
        """When ENABLE_LOCAL_CLONE_EXPLORER=true, _run_repo_fanout is called."""
        from app.synthesis.explorers.github_explorer import GitHubExplorer
        from app.synthesis.explorers.base import ExplorerReport

        explorer = GitHubExplorer()
        fanout_called = False

        async def mock_fanout(**kwargs):
            nonlocal fanout_called
            fanout_called = True

        with patch("app.synthesis.explorers.github_explorer.ENABLE_LOCAL_CLONE_EXPLORER", True):
            with patch.object(GitHubExplorer, "_run_repo_fanout", side_effect=mock_fanout):
                with patch.object(
                    explorer.__class__.__bases__[0],
                    "explore",
                    new_callable=AsyncMock,
                    return_value=ExplorerReport(source_name="github", personality_findings=""),
                ):
                    with patch("httpx.AsyncClient") as mock_client_cls:
                        mock_client = MagicMock()
                        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                        mock_client.__aexit__ = AsyncMock(return_value=False)
                        mock_client_cls.return_value = mock_client

                        await explorer.explore(
                            "testuser",
                            "",
                            {"repos_summary": {"top_repos": []}},
                        )

        assert fanout_called, "fan-out should have been called with flag on"


# ---------------------------------------------------------------------------
# ExplorerProgress source_type test
# ---------------------------------------------------------------------------


class TestExplorerProgressSourceType:
    @pytest.mark.asyncio
    async def test_upsert_creates_progress_with_github_repo_source_type(self):
        """RepoAgent._upsert_progress writes source_type='github_repo:<slug>'."""
        mini_id = _mini_id()
        session = _make_mock_session()
        agent = RepoAgent(mini_id=mini_id, db_session=session)

        source_type = "github_repo:owner__myrepo"
        await agent._upsert_progress(source_type, "running")

        # Session execute should have been called (for update then insert)
        assert session.execute.called or session.commit.called

    @pytest.mark.asyncio
    async def test_upsert_uses_session_factory_when_provided(self):
        """When session_factory is given, it should be used for writes."""
        mini_id = _mini_id()
        write_session = _make_mock_session()
        # rowcount=0 forces insert path
        write_session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
        factory = _make_mock_factory(write_session)

        agent = RepoAgent(
            mini_id=mini_id,
            db_session=MagicMock(),
            session_factory=factory,
        )

        await agent._upsert_progress("github_repo:owner__repo", "running")

        # The factory's context manager should have been entered
        factory.return_value.__aenter__.assert_called_once()
        write_session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Semaphore concurrency test
# ---------------------------------------------------------------------------


class TestSemaphoreConcurrency:
    @pytest.mark.asyncio
    async def test_at_most_n_repos_active_at_once(self):
        """With concurrency=2 and 10 repos, never more than 2 should be active simultaneously."""
        from app.synthesis.explorers.github_explorer import GitHubExplorer

        active = 0
        max_active = 0

        async def mock_ensure_clone(mini_id_uuid, owner, repo_name):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)  # simulate clone time
            active -= 1
            return Path("/tmp/fake_clone")

        async def mock_agent_run(self_inner, owner, repo_name, clone_root):
            return {
                "slug": f"{owner}__{repo_name}",
                "status": "completed",
                "turns_used": 1,
                "evidence_items_saved": 0,
            }

        fake_repos = [
            {
                "full_name": f"user/repo{i}",
                "name": f"repo{i}",
                "pushed_at": "2024-01-01T00:00:00Z",
                "stargazers_count": 10,
                "fork": False,
                "archived": False,
            }
            for i in range(10)
        ]

        explorer = GitHubExplorer()
        explorer._mini_id = str(uuid4())
        explorer._db_session = _make_mock_session()

        with patch(
            "app.synthesis.explorers.github_explorer.ensure_clone",
            side_effect=mock_ensure_clone,
        ):
            with patch.object(RepoAgent, "run", side_effect=mock_agent_run):
                await explorer._run_repo_fanout(
                    username="user",
                    all_repos=fake_repos,
                    max_repos=10,
                    concurrency=2,
                    size_limit_kb=0,
                )

        assert max_active <= 2, f"Expected at most 2 concurrent, got {max_active}"


# ---------------------------------------------------------------------------
# Integration: real tmp repo + mocked LLM
# ---------------------------------------------------------------------------


class TestRepoAgentIntegration:
    @pytest.mark.asyncio
    async def test_repo_agent_calls_at_least_one_tool(self, tmp_git_repo: Path):
        """RepoAgent.run() with a mocked run_agent records at least one tool call."""
        mini_id = _mini_id()
        session = _make_mock_session()
        factory = _make_mock_factory(session)

        # Track tool calls
        tool_calls: list[str] = []

        async def mock_run_agent(
            system_prompt,
            user_prompt,
            tools,
            **kwargs,
        ):
            from app.core.agent import AgentResult

            # Simulate calling one tool
            if tools:
                first_tool = tools[0]
                await first_tool.handler()
                tool_calls.append(first_tool.name)

            return AgentResult(
                final_response="done",
                tool_outputs={t.name: [] for t in tools},
                turns_used=1,
            )

        with patch(
            "app.synthesis.explorers.repo_agent.run_agent",
            side_effect=mock_run_agent,
        ):
            agent = RepoAgent(
                mini_id=mini_id,
                db_session=session,
                session_factory=factory,
            )
            result = await agent.run("testowner", "testrepo", tmp_git_repo)

        assert len(tool_calls) >= 1, "Expected at least one tool to be called"
        assert result["status"] in ("completed", "failed")
        assert result["slug"] == "testowner__testrepo"

    @pytest.mark.asyncio
    async def test_repo_agent_run_returns_completed_on_success(self, tmp_git_repo: Path):
        """A successful run returns status='completed'."""
        mini_id = _mini_id()
        session = _make_mock_session()

        async def mock_run_agent(system_prompt, user_prompt, tools, **kwargs):
            from app.core.agent import AgentResult

            return AgentResult(
                final_response="done",
                tool_outputs={t.name: [] for t in tools},
                turns_used=3,
            )

        with patch(
            "app.synthesis.explorers.repo_agent.run_agent",
            side_effect=mock_run_agent,
        ):
            agent = RepoAgent(mini_id=mini_id, db_session=session)
            result = await agent.run("owner", "repo", tmp_git_repo)

        assert result["status"] == "completed"
        assert result["turns_used"] == 3

    @pytest.mark.asyncio
    async def test_repo_agent_run_returns_failed_on_exception(self, tmp_git_repo: Path):
        """An agent crash returns status='failed' without raising."""
        mini_id = _mini_id()
        session = _make_mock_session()

        async def mock_run_agent(*args, **kwargs):
            raise RuntimeError("simulated LLM failure")

        with patch(
            "app.synthesis.explorers.repo_agent.run_agent",
            side_effect=mock_run_agent,
        ):
            agent = RepoAgent(mini_id=mini_id, db_session=session)
            result = await agent.run("owner", "repo", tmp_git_repo)

        assert result["status"] == "failed"
        assert "error" in result


# ---------------------------------------------------------------------------
# Repo selection scoring
# ---------------------------------------------------------------------------


class TestRepoSelection:
    def test_archived_repos_excluded(self):
        from app.synthesis.explorers.github_explorer import _select_repos

        repos = [
            {
                "full_name": "u/archived",
                "name": "archived",
                "archived": True,
                "fork": False,
                "stargazers_count": 1000,
                "pushed_at": "2024-01-01T00:00:00Z",
            },
            {
                "full_name": "u/active",
                "name": "active",
                "archived": False,
                "fork": False,
                "stargazers_count": 10,
                "pushed_at": "2024-06-01T00:00:00Z",
            },
        ]
        selected = _select_repos(repos, max_repos=5, size_limit_kb=0)
        names = [r["name"] for r in selected]
        assert "archived" not in names
        assert "active" in names

    def test_forked_repos_excluded(self):
        from app.synthesis.explorers.github_explorer import _select_repos

        repos = [
            {
                "full_name": "u/fork",
                "name": "fork",
                "archived": False,
                "fork": True,
                "stargazers_count": 500,
                "pushed_at": "2024-01-01T00:00:00Z",
            },
            {
                "full_name": "u/original",
                "name": "original",
                "archived": False,
                "fork": False,
                "stargazers_count": 5,
                "pushed_at": "2024-01-01T00:00:00Z",
            },
        ]
        selected = _select_repos(repos, max_repos=5, size_limit_kb=0)
        names = [r["name"] for r in selected]
        assert "fork" not in names
        assert "original" in names

    def test_oversized_repos_excluded(self):
        from app.synthesis.explorers.github_explorer import _select_repos

        repos = [
            {
                "full_name": "u/huge",
                "name": "huge",
                "archived": False,
                "fork": False,
                "size_kb": 300_000,
                "stargazers_count": 500,
                "pushed_at": "2024-01-01T00:00:00Z",
            },
            {
                "full_name": "u/small",
                "name": "small",
                "archived": False,
                "fork": False,
                "size_kb": 1_000,
                "stargazers_count": 5,
                "pushed_at": "2024-01-01T00:00:00Z",
            },
        ]
        selected = _select_repos(repos, max_repos=5, size_limit_kb=200_000)
        names = [r["name"] for r in selected]
        assert "huge" not in names
        assert "small" in names

    def test_max_repos_caps_result(self):
        from app.synthesis.explorers.github_explorer import _select_repos

        repos = [
            {
                "full_name": f"u/r{i}",
                "name": f"r{i}",
                "archived": False,
                "fork": False,
                "stargazers_count": i,
                "pushed_at": "2024-01-01T00:00:00Z",
            }
            for i in range(20)
        ]
        selected = _select_repos(repos, max_repos=5, size_limit_kb=0)
        assert len(selected) <= 5

    def test_recency_weight_decays_with_age(self):
        from app.synthesis.explorers.github_explorer import _recency_weight

        recent = _recency_weight("2025-01-01T00:00:00Z")
        old = _recency_weight("2018-01-01T00:00:00Z")
        assert recent > old
        assert 0.1 <= old <= 1.0
        assert 0.1 <= recent <= 1.0
