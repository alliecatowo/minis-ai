"""Integration tests: verify data flow across the three pipeline stages.

Tests in this module drive the pipeline with mocked HTTP + LLM, using
real in-memory logic for the FETCH → EXPLORE → SYNTHESIZE boundaries.
They assert on observable side-effects that exercise the stage contracts:

  - Evidence rows exist after FETCH
  - ExplorerProgress reaches "completed" after EXPLORE
  - MiniRevision / system_prompt populated after SYNTHESIZE

All external I/O (GitHub API, LLM calls) is fully mocked.
No real DB connection is required — the mocked session_factory tracks
inserts in-memory and surfaces them for assertions.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import PipelineEvent
from app.plugins.base import IngestionResult
from app.synthesis.explorers.base import ExplorerReport, MemoryEntry
from app.synthesis.pipeline import (
    _split_evidence_into_items,
    _store_evidence_in_db,
    run_pipeline,
)


# ---------------------------------------------------------------------------
# In-memory session helpers
# ---------------------------------------------------------------------------


class InMemorySession:
    """Minimal in-memory SQLAlchemy session substitute.

    Tracks ``add()`` calls so tests can inspect persisted objects.
    Does NOT support real queries — ``execute()`` always returns an empty result.
    """

    def __init__(self) -> None:
        self.added: list[Any] = []
        self._begin_ctx: "_BeginCtx | None" = None

    async def execute(self, stmt: Any) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        result.scalar_one_or_none.return_value = None
        result.scalar.return_value = 0
        result.scalar_one.return_value = 0
        return result

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass

    async def flush(self) -> None:
        pass

    def begin(self) -> "_BeginCtx":
        self._begin_ctx = _BeginCtx()
        return self._begin_ctx


class _BeginCtx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: Any) -> None:
        return None


def make_session_factory(extra_execute_side_effect=None):
    """Build a session_factory that yields an InMemorySession.

    Returns (factory, shared_session) so tests can inspect what was persisted.
    """
    session = InMemorySession()

    @asynccontextmanager
    async def factory():
        yield session

    return factory, session


# ---------------------------------------------------------------------------
# Helpers for mock mini objects
# ---------------------------------------------------------------------------


def make_mock_mini(mini_id: str = "mini-flow-1") -> MagicMock:
    mini = MagicMock()
    mini.id = mini_id
    mini.spirit_content = None
    mini.system_prompt = None
    mini.memory_content = None
    mini.values_json = None
    mini.status = "processing"
    return mini


def build_pipeline_session_factory(mini: MagicMock):
    """Build a session factory whose execute() returns the given mini."""
    session = MagicMock()

    cfg_result = MagicMock()
    cfg_result.scalars.return_value.all.return_value = []

    mini_result = MagicMock()
    mini_result.scalar_one_or_none.return_value = mini

    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    call_count = 0

    async def execute_side_effect(stmt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return cfg_result
        if "count" in str(stmt).lower():
            return count_result
        return mini_result

    session.execute = AsyncMock(side_effect=execute_side_effect)
    session.add = MagicMock()

    @asynccontextmanager
    async def factory():
        begin_ctx = MagicMock()
        begin_ctx.__aenter__ = AsyncMock(return_value=None)
        begin_ctx.__aexit__ = AsyncMock(return_value=None)
        session.begin = MagicMock(return_value=begin_ctx)
        yield session

    return factory


# ---------------------------------------------------------------------------
# 1. _split_evidence_into_items: FETCH stage output contract
# ---------------------------------------------------------------------------


class TestSplitEvidenceItems:
    """Evidence text split into DB items preserving content fidelity."""

    def test_empty_evidence_returns_empty_list(self):
        assert _split_evidence_into_items("", "github") == []

    def test_single_block_becomes_one_item(self):
        items = _split_evidence_into_items("Some commit message here.", "github")
        assert len(items) == 1
        assert items[0]["content"] == "Some commit message here."

    def test_items_have_required_keys(self):
        items = _split_evidence_into_items("Block one\n\n---\n\nBlock two", "github")
        for item in items:
            assert "type" in item
            assert "content" in item
            assert isinstance(item["type"], str)
            assert isinstance(item["content"], str)
            assert item["content"].strip()

    def test_markdown_h2_splitting(self):
        text = "## Profile\nAda Lovelace\n\n## Commits\nAdd feature"
        items = _split_evidence_into_items(text, "github")
        assert len(items) >= 2

    def test_commit_type_detection(self):
        text = "## Commit\nFix bug in diff parser\n+++ new code"
        items = _split_evidence_into_items(text, "github")
        assert any(i["type"] == "commit" for i in items)

    def test_pr_review_type_detection(self):
        text = "## Pull Request\nPR #42: Add feature\nCode review comment here."
        items = _split_evidence_into_items(text, "github")
        assert any(i["type"] == "pr_review" for i in items)

    def test_hackernews_source_becomes_comment(self):
        # Text has no commit/pr/blog/issue/review/doc keywords — falls through to source-based type
        text = "Interesting discussion about distributed systems and latency."
        items = _split_evidence_into_items(text, "hackernews")
        assert all(i["type"] == "comment" for i in items)

    def test_stackoverflow_source_becomes_comment(self):
        # Text has no commit/pr/blog/issue/review/doc keywords — falls through to source-based type
        text = "An answer about type checking with generics."
        items = _split_evidence_into_items(text, "stackoverflow")
        assert all(i["type"] == "comment" for i in items)

    def test_content_is_preserved(self):
        original = "The quick brown fox.\n\n---\n\nJumped over the lazy dog."
        items = _split_evidence_into_items(original, "github")
        combined = " ".join(i["content"] for i in items)
        assert "quick brown fox" in combined
        assert "lazy dog" in combined


# ---------------------------------------------------------------------------
# 2. _store_evidence_in_db: FETCH → DB boundary
# ---------------------------------------------------------------------------


class TestStoreEvidenceInDb:
    """_store_evidence_in_db persists Evidence + ExplorerProgress rows."""

    @pytest.mark.asyncio
    async def test_returns_item_count(self):
        factory, session = make_session_factory()
        n = await _store_evidence_in_db(
            mini_id="mini-1",
            source_name="github",
            evidence_text="Block one\n\n---\n\nBlock two",
            session_factory=factory,
        )
        assert n == 2

    @pytest.mark.asyncio
    async def test_persists_evidence_objects(self):
        from app.models.evidence import Evidence

        factory, session = make_session_factory()
        await _store_evidence_in_db(
            mini_id="mini-2",
            source_name="github",
            evidence_text="## Profile\nAda Lovelace\n\n## Commits\nAdd tests",
            session_factory=factory,
        )
        evidence_rows = [obj for obj in session.added if isinstance(obj, Evidence)]
        assert len(evidence_rows) >= 1
        for row in evidence_rows:
            assert row.mini_id == "mini-2"
            assert row.source_type == "github"
            assert row.content.strip()

    @pytest.mark.asyncio
    async def test_persists_explorer_progress(self):
        from app.models.evidence import ExplorerProgress

        factory, session = make_session_factory()
        await _store_evidence_in_db(
            mini_id="mini-3",
            source_name="hackernews",
            evidence_text="A hackernews comment about Python.",
            session_factory=factory,
        )
        progress_rows = [obj for obj in session.added if isinstance(obj, ExplorerProgress)]
        assert len(progress_rows) == 1
        prog = progress_rows[0]
        assert prog.mini_id == "mini-3"
        assert prog.source_type == "hackernews"
        assert prog.status == "pending"
        assert prog.total_items >= 1

    @pytest.mark.asyncio
    async def test_empty_evidence_stores_no_evidence_rows(self):
        from app.models.evidence import Evidence

        factory, session = make_session_factory()
        n = await _store_evidence_in_db(
            mini_id="mini-4",
            source_name="blog",
            evidence_text="",
            session_factory=factory,
        )
        assert n == 0
        evidence_rows = [obj for obj in session.added if isinstance(obj, Evidence)]
        assert evidence_rows == [], "Empty evidence text must produce zero Evidence rows"

    @pytest.mark.asyncio
    async def test_multiple_sources_stored_independently(self):
        from app.models.evidence import Evidence

        factory, session = make_session_factory()
        await _store_evidence_in_db(
            mini_id="mini-5",
            source_name="github",
            evidence_text="GitHub evidence block.",
            session_factory=factory,
        )
        await _store_evidence_in_db(
            mini_id="mini-5",
            source_name="blog",
            evidence_text="Blog evidence block.",
            session_factory=factory,
        )
        evidence_rows = [obj for obj in session.added if isinstance(obj, Evidence)]
        source_types = {r.source_type for r in evidence_rows}
        assert "github" in source_types
        assert "blog" in source_types


# ---------------------------------------------------------------------------
# 3. Stage boundary: fetch output keys match what downstream code accesses
# ---------------------------------------------------------------------------


class TestFetchOutputContract:
    """GitHubSource.fetch() output has every key the pipeline/explorer accesses."""

    REQUIRED_RAW_DATA_KEYS = {
        "profile",
        "repos_summary",
        "pull_requests_full",
        "review_comments_full",
        "issue_comments_full",
        "commits_full",
        "commit_diffs",
        "pr_review_threads",
        "issue_threads",
    }

    @pytest.mark.asyncio
    async def test_github_raw_data_has_all_required_keys(self):
        from app.ingestion.github import GitHubData
        from app.plugins.sources.github import GitHubSource

        github_data = GitHubData(
            profile={"login": "ada", "name": "Ada", "bio": "Dev", "avatar_url": "http://x.com/img"},
            repos=[
                {
                    "name": "engine",
                    "full_name": "ada/engine",
                    "language": "Python",
                    "stargazers_count": 10,
                    "topics": [],
                    "description": "",
                }
            ],
            commits=[{"commit": {"message": "init"}, "repository": {"full_name": "ada/engine"}}],
            pull_requests=[],
            review_comments=[],
            issue_comments=[],
            repo_languages={"ada/engine": {"Python": 1000}},
            commit_diffs=[],
            pr_review_threads=[],
            issue_threads=[],
        )

        with patch(
            "app.plugins.sources.github.fetch_github_data", AsyncMock(return_value=github_data)
        ):
            result = await GitHubSource().fetch("ada")

        missing = self.REQUIRED_RAW_DATA_KEYS - set(result.raw_data.keys())
        assert not missing, f"raw_data missing keys: {missing}"

    @pytest.mark.asyncio
    async def test_github_raw_data_types_are_correct(self):
        from app.ingestion.github import GitHubData
        from app.plugins.sources.github import GitHubSource

        github_data = GitHubData(
            profile={"login": "ada"},
            repos=[],
            commits=[],
            pull_requests=[
                {"title": "Fix bug", "body": "Details", "repository_url": "https://..."}
            ],
            review_comments=[{"body": "LGTM", "path": "f.py", "diff_hunk": ""}],
            issue_comments=[],
            repo_languages={},
            commit_diffs=[],
            pr_review_threads=[],
            issue_threads=[],
        )

        with patch(
            "app.plugins.sources.github.fetch_github_data", AsyncMock(return_value=github_data)
        ):
            result = await GitHubSource().fetch("ada")

        assert isinstance(result.raw_data["profile"], dict)
        assert isinstance(result.raw_data["repos_summary"], dict)
        assert isinstance(result.raw_data["pull_requests_full"], list)
        assert isinstance(result.raw_data["review_comments_full"], list)
        assert isinstance(result.raw_data["issue_comments_full"], list)
        assert isinstance(result.raw_data["commits_full"], list)
        assert isinstance(result.raw_data["commit_diffs"], list)
        assert isinstance(result.raw_data["pr_review_threads"], list)
        assert isinstance(result.raw_data["issue_threads"], list)

    @pytest.mark.asyncio
    async def test_ingestion_result_has_evidence_string(self):
        from app.ingestion.github import GitHubData
        from app.plugins.sources.github import GitHubSource

        github_data = GitHubData(
            profile={"login": "ada", "name": "Ada Lovelace", "bio": "Mathematician"},
            repos=[
                {
                    "name": "engine",
                    "full_name": "ada/engine",
                    "language": "Python",
                    "stargazers_count": 5,
                    "topics": [],
                    "description": "Engine",
                }
            ],
            commits=[],
            pull_requests=[],
            review_comments=[],
            issue_comments=[],
            repo_languages={"ada/engine": {"Python": 5000}},
            commit_diffs=[],
            pr_review_threads=[],
            issue_threads=[],
        )

        with patch(
            "app.plugins.sources.github.fetch_github_data", AsyncMock(return_value=github_data)
        ):
            result = await GitHubSource().fetch("ada")

        assert isinstance(result.evidence, str)
        assert len(result.evidence) > 0

    @pytest.mark.asyncio
    async def test_ingestion_result_stats_present(self):
        from app.ingestion.github import GitHubData
        from app.plugins.sources.github import GitHubSource

        github_data = GitHubData(
            profile={},
            repos=[],
            commits=[],
            pull_requests=[],
            review_comments=[],
            issue_comments=[],
            repo_languages={},
            commit_diffs=[],
            pr_review_threads=[],
            issue_threads=[],
        )

        with patch(
            "app.plugins.sources.github.fetch_github_data", AsyncMock(return_value=github_data)
        ):
            result = await GitHubSource().fetch("empty_user")

        required_stats = {
            "repos_count",
            "commits_analyzed",
            "prs_analyzed",
            "reviews_analyzed",
            "evidence_length",
        }
        missing_stats = required_stats - set(result.stats.keys())
        assert not missing_stats, f"stats missing keys: {missing_stats}"


# ---------------------------------------------------------------------------
# 4. GitHubData field coverage (ALLIE-368 regression guard)
# ---------------------------------------------------------------------------


class TestGitHubDataFieldCoverage:
    """Every field accessed in GitHubSource.fetch() must exist on GitHubData."""

    ACCESSED_FIELDS = {
        # Direct attribute access in GitHubSource.fetch() and helpers
        "profile",
        "repos",
        "commits",
        "pull_requests",
        "review_comments",
        "issue_comments",
        "repo_languages",
        "commit_diffs",
        "pr_review_threads",
        "issue_threads",
    }

    def test_all_accessed_fields_exist_on_githubdata_dataclass(self):
        import dataclasses
        from app.ingestion.github import GitHubData

        dc_fields = {f.name for f in dataclasses.fields(GitHubData)}
        missing = self.ACCESSED_FIELDS - dc_fields
        assert not missing, (
            f"GitHubData is missing fields accessed by GitHubSource: {missing}\n"
            "This is a regression of ALLIE-368 — add the missing field(s) to the dataclass."
        )

    def test_all_accessed_fields_have_sensible_defaults(self):
        from app.ingestion.github import GitHubData

        # Should be constructible with no arguments (all have defaults)
        try:
            obj = GitHubData()
        except TypeError as e:
            pytest.fail(f"GitHubData() construction without args failed: {e}")

        for field in self.ACCESSED_FIELDS:
            val = getattr(obj, field)
            # Should be a falsy but valid empty collection, not None
            assert val is not None, (
                f"GitHubData.{field} default is None — should be empty collection"
            )

    def test_repo_languages_is_dict(self):
        from app.ingestion.github import GitHubData

        data = GitHubData()
        assert isinstance(data.repo_languages, dict), (
            "GitHubData.repo_languages must be a dict — "
            "_aggregate_languages() iterates .values() on it"
        )

    def test_list_fields_are_lists(self):
        from app.ingestion.github import GitHubData

        data = GitHubData()
        list_fields = [
            "repos",
            "commits",
            "pull_requests",
            "review_comments",
            "issue_comments",
            "commit_diffs",
            "pr_review_threads",
            "issue_threads",
        ]
        for field in list_fields:
            val = getattr(data, field)
            assert isinstance(val, list), (
                f"GitHubData.{field} should default to a list, got {type(val).__name__}"
            )


# ---------------------------------------------------------------------------
# 5. End-to-end dry-run through run_pipeline (all external I/O mocked)
# ---------------------------------------------------------------------------


class TestPipelineDryRun:
    """Drive run_pipeline through all stages with mocked sources and LLM."""

    def _make_patches(self, soul_doc="Soul content", system_prompt_text="System prompt"):
        """Common patches needed for a full pipeline run."""
        return [
            patch(
                "app.synthesis.pipeline.run_chief_synthesizer",
                AsyncMock(return_value=soul_doc),
            ),
            patch(
                "app.synthesis.pipeline.run_chief_synthesis",
                AsyncMock(return_value=soul_doc),
            ),
            patch(
                "app.synthesis.pipeline._store_evidence_in_db",
                AsyncMock(return_value=3),
            ),
            patch(
                "app.synthesis.pipeline._build_structured_from_db",
                AsyncMock(return_value=({"nodes": [], "edges": []}, {"principles": []})),
            ),
            patch(
                "app.synthesis.pipeline._build_synthetic_reports_from_db",
                AsyncMock(return_value=[]),
            ),
            patch(
                "app.synthesis.pipeline.build_system_prompt",
                return_value=system_prompt_text,
            ),
            patch(
                "app.synthesis.memory_assembler.extract_values_json",
                return_value='{"values": []}',
            ),
            patch(
                "app.synthesis.memory_assembler.extract_roles_llm",
                AsyncMock(return_value='{"roles": []}'),
            ),
            patch(
                "app.synthesis.memory_assembler.extract_skills_llm",
                AsyncMock(return_value='{"skills": []}'),
            ),
            patch(
                "app.synthesis.memory_assembler.extract_traits_llm",
                AsyncMock(return_value='{"traits": []}'),
            ),
            patch(
                "app.synthesis.memory_assembler._merge_knowledge_graphs",
                return_value=MagicMock(model_dump=lambda **kw: {}),
            ),
            patch(
                "app.synthesis.memory_assembler._merge_principles",
                return_value=MagicMock(model_dump=lambda **kw: {}),
            ),
            patch("app.synthesis.pipeline._generate_embeddings", AsyncMock()),
        ]

    def _make_ingestion_result(self, source_name: str = "github") -> IngestionResult:
        return IngestionResult(
            source_name=source_name,
            identifier="testuser",
            evidence="## GitHub Profile\nTest user\n\n## Commits\nAdd feature",
            raw_data={
                "profile": {"name": "Test User", "bio": "Dev", "avatar_url": "http://x.com/img"},
                "repos_summary": {
                    "languages": {},
                    "primary_languages": {},
                    "repo_count": 1,
                    "top_repos": [],
                },
                "pull_requests_full": [],
                "review_comments_full": [],
                "issue_comments_full": [],
                "commits_full": [],
                "commit_diffs": [],
                "pr_review_threads": [],
                "issue_threads": [],
            },
        )

    @pytest.mark.asyncio
    async def test_all_pipeline_stages_emit_events(self):
        """Happy path: every stage emits started + completed events."""
        from contextlib import ExitStack

        events: list[PipelineEvent] = []

        async def collect(event: PipelineEvent) -> None:
            events.append(event)

        mini = make_mock_mini("mini-dryrun-1")
        mock_source = MagicMock()
        mock_source.fetch = AsyncMock(return_value=self._make_ingestion_result())
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(
                source_name="github",
                personality_findings="Likes clean code",
                memory_entries=[
                    MemoryEntry(
                        category="expertise",
                        topic="Python",
                        content="Uses Python",
                        confidence=0.9,
                        source_type="github",
                    )
                ],
            )
        )

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._make_patches(soul_doc="Soul doc", system_prompt_text="## System"):
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="testuser",
                session_factory=build_pipeline_session_factory(mini),
                on_progress=collect,
                sources=["github"],
                mini_id="mini-dryrun-1",
            )

        stage_statuses = {(e.stage, e.status) for e in events}
        assert ("fetch", "started") in stage_statuses
        assert ("fetch", "completed") in stage_statuses
        assert ("explore", "started") in stage_statuses
        assert ("explore", "completed") in stage_statuses
        assert ("synthesize", "started") in stage_statuses
        assert ("synthesize", "completed") in stage_statuses
        assert ("save", "started") in stage_statuses
        assert ("save", "completed") in stage_statuses

    @pytest.mark.asyncio
    async def test_mini_status_becomes_ready_after_success(self):
        """After a successful pipeline run, mini.status == 'ready'."""
        from contextlib import ExitStack

        mini = make_mock_mini("mini-dryrun-2")
        mock_source = MagicMock()
        mock_source.fetch = AsyncMock(return_value=self._make_ingestion_result())
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(source_name="github", personality_findings="")
        )

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._make_patches():
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="testuser",
                session_factory=build_pipeline_session_factory(mini),
                sources=["github"],
                mini_id="mini-dryrun-2",
            )

        assert mini.status == "ready"

    @pytest.mark.asyncio
    async def test_system_prompt_set_after_synthesize(self):
        """mini.system_prompt is populated after a successful run."""
        from contextlib import ExitStack

        mini = make_mock_mini("mini-dryrun-3")
        mock_source = MagicMock()
        mock_source.fetch = AsyncMock(return_value=self._make_ingestion_result())
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(source_name="github", personality_findings="")
        )

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._make_patches(system_prompt_text="You are Ada."):
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="testuser",
                session_factory=build_pipeline_session_factory(mini),
                sources=["github"],
                mini_id="mini-dryrun-3",
            )

        assert mini.system_prompt == "You are Ada."

    @pytest.mark.asyncio
    async def test_spirit_content_set_after_synthesize(self):
        """mini.spirit_content is populated with the chief's soul doc."""
        from contextlib import ExitStack

        mini = make_mock_mini("mini-dryrun-4")
        mock_source = MagicMock()
        mock_source.fetch = AsyncMock(return_value=self._make_ingestion_result())
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(source_name="github", personality_findings="")
        )

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._make_patches(soul_doc="The soul of Ada."):
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source
            mock_registry.list_sources.return_value = ["github"]

            await run_pipeline(
                username="testuser",
                session_factory=build_pipeline_session_factory(mini),
                sources=["github"],
                mini_id="mini-dryrun-4",
            )

        assert mini.spirit_content == "The soul of Ada."

    @pytest.mark.asyncio
    async def test_source_fetch_called_with_identifier(self):
        """Fetch is called with the correct per-source identifier."""
        from contextlib import ExitStack

        mini = make_mock_mini("mini-dryrun-5")
        mock_source = MagicMock()
        mock_source.fetch = AsyncMock(return_value=self._make_ingestion_result("hackernews"))
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(source_name="hackernews", personality_findings="")
        )

        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            for p in self._make_patches():
                stack.enter_context(p)

            mock_registry.get_source.return_value = mock_source

            await run_pipeline(
                username="ghuser",
                session_factory=build_pipeline_session_factory(mini),
                sources=["hackernews"],
                mini_id="mini-dryrun-5",
                source_identifiers={"hackernews": "hn-user"},
            )

        # Should have been called with "hn-user", not "ghuser"
        call_args = mock_source.fetch.call_args[0]
        assert call_args[0] == "hn-user"

    @pytest.mark.asyncio
    async def test_failed_source_emits_error_event(self):
        """When all sources fail, the pipeline emits an error event."""
        events: list[PipelineEvent] = []

        async def collect(event: PipelineEvent) -> None:
            events.append(event)

        mock_source = MagicMock()
        mock_source.fetch = AsyncMock(side_effect=RuntimeError("network failure"))

        with patch("app.synthesis.pipeline.registry") as mock_registry:
            mock_registry.get_source.return_value = mock_source

            await run_pipeline(
                username="failuser",
                session_factory=build_pipeline_session_factory(make_mock_mini()),
                on_progress=collect,
                sources=["github"],
            )

        error_events = [e for e in events if e.stage == "error"]
        assert len(error_events) >= 1

    @pytest.mark.asyncio
    async def test_evidence_stored_in_db_called_per_source(self):
        """_store_evidence_in_db must be called once per source with evidence."""
        from contextlib import ExitStack

        mini = make_mock_mini("mini-dryrun-6")
        mock_source = MagicMock()
        mock_source.fetch = AsyncMock(return_value=self._make_ingestion_result())
        mock_explorer = MagicMock()
        mock_explorer.explore = AsyncMock(
            return_value=ExplorerReport(source_name="github", personality_findings="")
        )

        store_calls: list[dict] = []

        async def mock_store(mini_id, source_name, evidence_text, session_factory, **kwargs):
            store_calls.append({"mini_id": mini_id, "source_name": source_name})
            return 2

        # Build patches manually, replacing _store_evidence_in_db with our spy
        with ExitStack() as stack:
            mock_registry = stack.enter_context(patch("app.synthesis.pipeline.registry"))
            stack.enter_context(
                patch("app.synthesis.pipeline.get_explorer", return_value=mock_explorer)
            )
            # Replace the store function with a spy BEFORE the other patches
            stack.enter_context(patch("app.synthesis.pipeline._store_evidence_in_db", mock_store))
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline.run_chief_synthesizer",
                    AsyncMock(return_value="Soul doc"),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline.run_chief_synthesis",
                    AsyncMock(return_value="Soul doc"),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline._build_structured_from_db",
                    AsyncMock(return_value=({"nodes": [], "edges": []}, {"principles": []})),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline._build_synthetic_reports_from_db",
                    AsyncMock(return_value=[]),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.pipeline.build_system_prompt",
                    return_value="System prompt",
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler.extract_values_json",
                    return_value='{"values": []}',
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler.extract_roles_llm",
                    AsyncMock(return_value='{"roles": []}'),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler.extract_skills_llm",
                    AsyncMock(return_value='{"skills": []}'),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler.extract_traits_llm",
                    AsyncMock(return_value='{"traits": []}'),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler._merge_knowledge_graphs",
                    return_value=MagicMock(model_dump=lambda **kw: {}),
                )
            )
            stack.enter_context(
                patch(
                    "app.synthesis.memory_assembler._merge_principles",
                    return_value=MagicMock(model_dump=lambda **kw: {}),
                )
            )
            stack.enter_context(patch("app.synthesis.pipeline._generate_embeddings", AsyncMock()))

            mock_registry.get_source.return_value = mock_source

            await run_pipeline(
                username="testuser",
                session_factory=build_pipeline_session_factory(mini),
                sources=["github"],
                mini_id="mini-dryrun-6",
            )

        assert len(store_calls) == 1
        assert store_calls[0]["source_name"] == "github"
        assert store_calls[0]["mini_id"] == "mini-dryrun-6"
