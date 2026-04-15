"""Tests for individual explorer classes and the explorer registry.

Covers:
- Each explorer's system_prompt() returns a non-empty string
- Each explorer's user_prompt() returns a non-empty string containing username
- Explorer self-registration via register_explorer()
- get_explorer() instantiates the correct class
- ExplorerReport and MemoryEntry Pydantic model construction
"""

from __future__ import annotations

import pytest

from app.synthesis.explorers import EXPLORER_MAP, get_explorer, register_explorer
from app.synthesis.explorers.base import Explorer, ExplorerReport, MemoryEntry


# ---------------------------------------------------------------------------
# Import all explorer modules so they register themselves
# ---------------------------------------------------------------------------

import app.synthesis.explorers.github_explorer  # noqa: F401
import app.synthesis.explorers.blog_explorer  # noqa: F401
import app.synthesis.explorers.claude_code_explorer  # noqa: F401
import app.synthesis.explorers.hackernews_explorer  # noqa: F401
import app.synthesis.explorers.stackoverflow_explorer  # noqa: F401
import app.synthesis.explorers.devto_explorer  # noqa: F401
import app.synthesis.explorers.website_explorer  # noqa: F401


# ---------------------------------------------------------------------------
# Explorer registry
# ---------------------------------------------------------------------------


KNOWN_EXPLORERS = [
    "github",
    "blog",
    "claude_code",
    "hackernews",
    "stackoverflow",
    "devblog",
    "website",
]


class TestExplorerRegistry:
    def test_all_known_explorers_are_registered(self):
        for name in KNOWN_EXPLORERS:
            assert name in EXPLORER_MAP, f"Explorer '{name}' not registered"

    def test_get_explorer_returns_explorer_instance(self):
        for name in KNOWN_EXPLORERS:
            explorer = get_explorer(name)
            assert isinstance(explorer, Explorer), (
                f"get_explorer('{name}') did not return an Explorer"
            )

    def test_get_explorer_unknown_raises_key_error(self):
        with pytest.raises(KeyError):
            get_explorer("nonexistent_source")

    def test_register_custom_explorer(self):
        """Custom explorer classes should register and retrieve correctly."""
        class CustomExplorer(Explorer):
            source_name = "custom_test"

            def system_prompt(self) -> str:
                return "Custom system prompt"

            def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
                return f"Custom prompt for {username}"

        register_explorer("custom_test", CustomExplorer)
        assert "custom_test" in EXPLORER_MAP
        explorer = get_explorer("custom_test")
        assert isinstance(explorer, CustomExplorer)

        # Cleanup
        del EXPLORER_MAP["custom_test"]

    def test_overwrite_explorer_replaces_registration(self):
        """Re-registering an explorer should overwrite the previous entry."""
        class FirstExplorer(Explorer):
            source_name = "overwrite_test"
            def system_prompt(self) -> str: return "first"
            def user_prompt(self, u, e, r): return "first"

        class SecondExplorer(Explorer):
            source_name = "overwrite_test"
            def system_prompt(self) -> str: return "second"
            def user_prompt(self, u, e, r): return "second"

        register_explorer("overwrite_test", FirstExplorer)
        register_explorer("overwrite_test", SecondExplorer)
        assert EXPLORER_MAP["overwrite_test"] is SecondExplorer

        # Cleanup
        del EXPLORER_MAP["overwrite_test"]


# ---------------------------------------------------------------------------
# Per-explorer prompt tests
# ---------------------------------------------------------------------------


class TestGitHubExplorerPrompts:
    def setup_method(self):
        self.explorer = get_explorer("github")

    def test_system_prompt_non_empty(self):
        assert self.explorer.system_prompt()

    def test_system_prompt_is_string(self):
        assert isinstance(self.explorer.system_prompt(), str)

    def test_system_prompt_substantial(self):
        assert len(self.explorer.system_prompt()) > 100

    def test_user_prompt_returns_string(self):
        result = self.explorer.user_prompt("torvalds", "some evidence", {})
        assert isinstance(result, str)

    def test_user_prompt_contains_username(self):
        result = self.explorer.user_prompt("torvalds", "some evidence", {})
        assert "torvalds" in result

    def test_user_prompt_non_empty(self):
        result = self.explorer.user_prompt("user", "evidence", {})
        assert result


class TestBlogExplorerPrompts:
    def setup_method(self):
        self.explorer = get_explorer("blog")

    def test_system_prompt_non_empty(self):
        assert self.explorer.system_prompt()

    def test_system_prompt_is_string(self):
        assert isinstance(self.explorer.system_prompt(), str)

    def test_user_prompt_contains_username(self):
        result = self.explorer.user_prompt("dhh", "evidence", {})
        assert "dhh" in result

    def test_user_prompt_is_string(self):
        result = self.explorer.user_prompt("dhh", "evidence", {})
        assert isinstance(result, str)


class TestClaudeCodeExplorerPrompts:
    def setup_method(self):
        self.explorer = get_explorer("claude_code")

    def test_system_prompt_non_empty(self):
        assert self.explorer.system_prompt()

    def test_user_prompt_contains_username(self):
        result = self.explorer.user_prompt("testuser", "evidence", {})
        assert "testuser" in result


class TestHackerNewsExplorerPrompts:
    def setup_method(self):
        self.explorer = get_explorer("hackernews")

    def test_system_prompt_non_empty(self):
        assert self.explorer.system_prompt()

    def test_user_prompt_contains_username(self):
        result = self.explorer.user_prompt("pg", "evidence", {})
        assert "pg" in result


class TestStackOverflowExplorerPrompts:
    def setup_method(self):
        self.explorer = get_explorer("stackoverflow")

    def test_system_prompt_non_empty(self):
        assert self.explorer.system_prompt()

    def test_user_prompt_contains_username(self):
        result = self.explorer.user_prompt("jsmith", "evidence", {})
        assert "jsmith" in result


class TestDevBlogExplorerPrompts:
    def setup_method(self):
        self.explorer = get_explorer("devblog")

    def test_system_prompt_non_empty(self):
        assert self.explorer.system_prompt()

    def test_user_prompt_contains_username(self):
        result = self.explorer.user_prompt("devuser", "evidence", {})
        assert "devuser" in result


class TestWebsiteExplorerPrompts:
    def setup_method(self):
        self.explorer = get_explorer("website")

    def test_system_prompt_non_empty(self):
        assert self.explorer.system_prompt()

    def test_user_prompt_contains_username(self):
        result = self.explorer.user_prompt("webdev", "evidence", {})
        assert "webdev" in result


# ---------------------------------------------------------------------------
# source_name attribute
# ---------------------------------------------------------------------------


class TestExplorerSourceName:
    @pytest.mark.parametrize(
        "source_name,expected",
        [
            ("github", "github"),
            ("blog", "blog"),
            ("claude_code", "claude_code"),
            ("hackernews", "hackernews"),
            ("stackoverflow", "stackoverflow"),
            ("devblog", "devblog"),
            ("website", "website"),
        ],
    )
    def test_source_name_matches_registration_key(self, source_name, expected):
        explorer = get_explorer(source_name)
        assert explorer.source_name == expected


# ---------------------------------------------------------------------------
# ExplorerReport model
# ---------------------------------------------------------------------------


class TestExplorerReport:
    def test_minimal_construction(self):
        report = ExplorerReport(
            source_name="github",
            personality_findings="Developer prefers functional style.",
        )
        assert report.source_name == "github"
        assert report.personality_findings == "Developer prefers functional style."

    def test_default_empty_lists(self):
        report = ExplorerReport(source_name="github", personality_findings="")
        assert report.memory_entries == []
        assert report.behavioral_quotes == []

    def test_with_memory_entries(self):
        entry = MemoryEntry(
            category="expertise",
            topic="Python",
            content="Expert in Python",
            confidence=0.9,
            source_type="github",
        )
        report = ExplorerReport(
            source_name="github",
            personality_findings="",
            memory_entries=[entry],
        )
        assert len(report.memory_entries) == 1
        assert report.memory_entries[0].topic == "Python"

    def test_with_behavioral_quotes(self):
        quote = {"context": "code review", "quote": "This is wrong.", "signal_type": "directness"}
        report = ExplorerReport(
            source_name="github",
            personality_findings="",
            behavioral_quotes=[quote],
        )
        assert len(report.behavioral_quotes) == 1

    def test_confidence_summary_defaults_to_empty(self):
        report = ExplorerReport(source_name="blog", personality_findings="")
        assert report.confidence_summary == ""

    def test_context_evidence_defaults_to_empty_dict(self):
        report = ExplorerReport(source_name="blog", personality_findings="")
        assert report.context_evidence == {}


# ---------------------------------------------------------------------------
# MemoryEntry model
# ---------------------------------------------------------------------------


class TestMemoryEntry:
    def test_valid_construction(self):
        entry = MemoryEntry(
            category="projects",
            topic="Linux kernel",
            content="Maintains Linux kernel since 1991",
            confidence=0.99,
            source_type="github",
            evidence_quote="I wrote the kernel.",
        )
        assert entry.category == "projects"
        assert entry.confidence == 0.99

    def test_confidence_bounds_valid(self):
        entry = MemoryEntry(
            category="c", topic="t", content="x",
            confidence=0.0, source_type="github",
        )
        assert entry.confidence == 0.0

        entry2 = MemoryEntry(
            category="c", topic="t", content="x",
            confidence=1.0, source_type="github",
        )
        assert entry2.confidence == 1.0

    def test_evidence_quote_defaults_to_empty(self):
        entry = MemoryEntry(
            category="c", topic="t", content="x",
            confidence=0.5, source_type="github",
        )
        assert entry.evidence_quote == ""

    def test_confidence_out_of_bounds_raises(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            MemoryEntry(
                category="c", topic="t", content="x",
                confidence=1.5, source_type="github",
            )

    def test_confidence_below_zero_raises(self):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            MemoryEntry(
                category="c", topic="t", content="x",
                confidence=-0.1, source_type="github",
            )
