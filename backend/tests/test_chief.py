"""Tests for backend/app/synthesis/chief.py.

Covers:
- SECTION_ORDER constant
- Tool construction (correct names, schemas) in run_chief_synthesizer
- Tool handlers: search_findings, get_findings_by_category, get_all_quotes,
  get_knowledge_graph, get_principles, get_explorer_summaries
- write_section logic
- finish logic
- Soul document assembly (Identity Core prefix)
- run_chief_synthesis backward-compatible alias
- System prompt existence / content
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.synthesis.chief import (
    CHIEF_FINAL_SYNTHESIS_PROMPT,
    SECTION_ORDER,
    SYSTEM_PROMPT,
    run_chief_synthesis,
    run_chief_synthesizer,
)
from app.core.agent import AgentTool, AgentResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestSectionOrder:
    def test_contains_eight_sections(self):
        assert len(SECTION_ORDER) == 8

    def test_known_sections_present(self):
        expected = [
            "Identity Core",
            "Voice & Style",
            "Personality & Emotional Patterns",
            "Values & Beliefs",
            "Anti-Values & DON'Ts",
            "Conflict & Pushback",
            "Voice Samples",
            "Quirks & Imperfection",
        ]
        assert SECTION_ORDER == expected

    def test_identity_core_is_first(self):
        assert SECTION_ORDER[0] == "Identity Core"

    def test_voice_style_is_second(self):
        assert SECTION_ORDER[1] == "Voice & Style"


class TestSystemPrompt:
    def test_system_prompt_is_non_empty(self):
        assert len(SYSTEM_PROMPT) > 100

    def test_mentions_second_person_writing(self):
        # Ensure prompt instructs second-person voice
        assert "second person" in SYSTEM_PROMPT.lower() or "You ARE" in SYSTEM_PROMPT

    def test_mentions_forgery_manual_anchor(self):
        assert "Forgery Manual" in SYSTEM_PROMPT or "forgery manual" in SYSTEM_PROMPT.lower()

    def test_mentions_all_tool_names(self):
        for tool_name in [
            "get_explorer_summaries",
            "search_findings",
            "get_findings_by_category",
            "get_all_quotes",
            "get_knowledge_graph",
            "get_principles",
            "write_section",
            "finish",
        ]:
            assert tool_name in SYSTEM_PROMPT, f"Tool '{tool_name}' missing from SYSTEM_PROMPT"

    def test_prompts_forbid_meta_label_prefixes(self):
        assert "meta labels" in SYSTEM_PROMPT
        assert "meta labels" in CHIEF_FINAL_SYNTHESIS_PROMPT


# ---------------------------------------------------------------------------
# run_chief_synthesizer — tool construction
# ---------------------------------------------------------------------------


def _make_mock_db_session(mini=None):
    """Return a mock async DB session."""
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    return session


def _make_mock_mini(mini_id="test-mini-id", username="testuser"):
    mini = MagicMock()
    mini.id = mini_id
    mini.username = username
    mini.knowledge_graph_json = None
    mini.principles_json = None
    return mini


class TestRunChiefSynthesizerToolConstruction:
    """Verify tool names and schema shapes without making LLM calls."""

    @pytest.mark.asyncio
    async def test_tool_names_and_count(self):
        """run_chief_synthesizer should build exactly 8 tools with the right names."""
        mini = _make_mock_mini()
        session = _make_mock_db_session(mini)

        captured_tools: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured_tools.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            # Will produce empty sections but not crash
            await run_chief_synthesizer(mini_id="test-mini-id", db_session=session)

        tool_names = [t.name for t in captured_tools]
        assert "search_findings" in tool_names
        assert "get_findings_by_category" in tool_names
        assert "get_all_quotes" in tool_names
        assert "get_knowledge_graph" in tool_names
        assert "get_principles" in tool_names
        assert "get_explorer_summaries" in tool_names
        assert "write_section" in tool_names
        assert "finish" in tool_names
        assert "get_voice_profile" in tool_names
        assert len(tool_names) == 9

    @pytest.mark.asyncio
    async def test_search_findings_schema(self):
        """search_findings tool must require 'query' and optionally accept 'source_type'."""
        mini = _make_mock_mini()
        session = _make_mock_db_session(mini)

        captured_tools: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured_tools.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id="test-mini-id", db_session=session)

        sf_tool = next(t for t in captured_tools if t.name == "search_findings")
        params = sf_tool.parameters
        assert params["type"] == "object"
        assert "query" in params["properties"]
        assert "source_type" in params["properties"]
        assert "query" in params["required"]
        assert "source_type" not in params.get("required", [])

    @pytest.mark.asyncio
    async def test_write_section_schema(self):
        """write_section must require both 'section_name' and 'content'."""
        mini = _make_mock_mini()
        session = _make_mock_db_session(mini)

        captured_tools: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured_tools.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id="test-mini-id", db_session=session)

        ws_tool = next(t for t in captured_tools if t.name == "write_section")
        params = ws_tool.parameters
        assert "section_name" in params["properties"]
        assert "content" in params["properties"]
        assert "section_name" in params["required"]
        assert "content" in params["required"]

    @pytest.mark.asyncio
    async def test_finish_tool_has_empty_schema(self):
        """finish tool should have no required properties."""
        mini = _make_mock_mini()
        session = _make_mock_db_session(mini)

        captured_tools: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured_tools.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id="test-mini-id", db_session=session)

        finish_tool = next(t for t in captured_tools if t.name == "finish")
        params = finish_tool.parameters
        assert params.get("required", []) == []

    @pytest.mark.asyncio
    async def test_raises_when_mini_not_found(self):
        """If mini is not in the DB, ValueError must be raised."""
        session = _make_mock_db_session(mini=None)

        with patch("app.synthesis.chief.run_agent", AsyncMock()):
            with pytest.raises(ValueError, match="Mini not found"):
                await run_chief_synthesizer(mini_id="no-such-id", db_session=session)


# ---------------------------------------------------------------------------
# Tool handlers — tested by calling them directly via the captured handler
# ---------------------------------------------------------------------------


class TestChiefToolHandlers:
    """Invoke the actual async handler functions captured from run_chief_synthesizer."""

    async def _capture_handlers(self, mini):
        """Run run_chief_synthesizer with a fake agent and return {name: handler}."""
        session = _make_mock_db_session(mini)
        captured: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        return {t.name: t.handler for t in captured}, session

    # ── write_section ──

    @pytest.mark.asyncio
    async def test_write_section_stores_content(self):
        mini = _make_mock_mini()
        handlers, _ = await self._capture_handlers(mini)
        result = await handlers["write_section"](
            section_name="Identity Core", content="You ARE testuser."
        )
        assert "Identity Core" in result
        assert "written" in result.lower()

    @pytest.mark.asyncio
    async def test_write_section_returns_remaining_sections(self):
        mini = _make_mock_mini()
        handlers, _ = await self._capture_handlers(mini)
        result = await handlers["write_section"](
            section_name="Voice & Style", content="You speak tersely."
        )
        assert "Remaining" in result
        # Identity Core should still be remaining
        assert "Identity Core" in result

    @pytest.mark.asyncio
    async def test_write_section_overwrites_existing(self):
        mini = _make_mock_mini()
        handlers, _ = await self._capture_handlers(mini)

        await handlers["write_section"](section_name="Identity Core", content="first")
        result = await handlers["write_section"](section_name="Identity Core", content="second")
        # Should mention the section was written (overwritten)
        assert "Identity Core" in result

    # ── finish ──

    @pytest.mark.asyncio
    async def test_finish_rejected_when_sections_missing(self):
        mini = _make_mock_mini()
        handlers, _ = await self._capture_handlers(mini)
        result = await handlers["finish"]()
        assert "missing" in result.lower() or "cannot finish" in result.lower()

    @pytest.mark.asyncio
    async def test_finish_accepted_when_all_sections_written(self):
        mini = _make_mock_mini()
        handlers, _ = await self._capture_handlers(mini)

        # Write all 8 sections
        for section in SECTION_ORDER:
            await handlers["write_section"](section_name=section, content=f"Content for {section}.")

        result = await handlers["finish"]()
        assert "finalized" in result.lower() or "soul document" in result.lower()

    # ── get_knowledge_graph ──

    @pytest.mark.asyncio
    async def test_get_knowledge_graph_no_data(self):
        mini = _make_mock_mini()
        mini.knowledge_graph_json = None
        handlers, _ = await self._capture_handlers(mini)
        result = await handlers["get_knowledge_graph"]()
        assert "no knowledge graph" in result.lower() or "not available" in result.lower()

    @pytest.mark.asyncio
    async def test_get_knowledge_graph_with_data(self):
        mini = _make_mock_mini()
        mini.knowledge_graph_json = {
            "nodes": [{"name": "Python", "type": "skill", "depth": 1, "confidence": 0.9}],
            "edges": [{"source": "Python", "target": "Django", "relation": "uses", "weight": 0.8}],
        }
        handlers, _ = await self._capture_handlers(mini)
        result = await handlers["get_knowledge_graph"]()
        assert "Python" in result
        assert "Django" in result
        assert "Knowledge Graph" in result

    # ── get_principles ──

    @pytest.mark.asyncio
    async def test_get_principles_no_data(self):
        mini = _make_mock_mini()
        mini.principles_json = None
        handlers, _ = await self._capture_handlers(mini)
        result = await handlers["get_principles"]()
        assert "no principles" in result.lower()

    @pytest.mark.asyncio
    async def test_get_principles_with_data(self):
        mini = _make_mock_mini()
        mini.principles_json = {
            "principles": [
                {
                    "trigger": "bad code spotted",
                    "action": "call it out directly",
                    "value": "quality",
                    "intensity": "high",
                }
            ]
        }
        handlers, _ = await self._capture_handlers(mini)
        result = await handlers["get_principles"]()
        assert "bad code spotted" in result
        assert "call it out directly" in result
        assert "Principles" in result

    @pytest.mark.asyncio
    async def test_get_principles_empty_list(self):
        mini = _make_mock_mini()
        mini.principles_json = {"principles": []}
        handlers, _ = await self._capture_handlers(mini)
        result = await handlers["get_principles"]()
        assert "no principles" in result.lower()

    # ── search_findings ──

    @pytest.mark.asyncio
    async def test_search_findings_returns_no_findings_message(self):
        """When DB returns no findings, a sensible message is returned."""
        mini = _make_mock_mini()

        # DB session returns empty result for all queries
        session = _make_mock_db_session(mini)
        captured: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        handlers = {t.name: t.handler for t in captured}
        result = await handlers["search_findings"](query="clean code")
        assert "no findings" in result.lower()

    @pytest.mark.asyncio
    async def test_search_findings_with_results(self):
        """When DB returns findings, they are formatted correctly."""
        from app.models.evidence import ExplorerFinding

        mini = _make_mock_mini()
        session = MagicMock()

        mock_finding = MagicMock(spec=ExplorerFinding)
        mock_finding.source_type = "github"
        mock_finding.category = "expertise"
        mock_finding.confidence = 0.85
        mock_finding.content = "Expert in clean code practices"

        # First execute call: Mini lookup
        mini_result = MagicMock()
        mini_result.scalar_one_or_none.return_value = mini

        # Second execute call: findings search
        findings_result = MagicMock()
        findings_result.scalars.return_value.all.return_value = [mock_finding]

        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mini_result
            return findings_result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        captured: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        handlers = {t.name: t.handler for t in captured}
        result = await handlers["search_findings"](query="clean code")
        assert "Expert in clean code practices" in result
        assert "github" in result
        assert "0.85" in result

    # ── get_findings_by_category ──

    @pytest.mark.asyncio
    async def test_get_findings_by_category_no_findings(self):
        """When category has no findings, available categories are shown."""

        mini = _make_mock_mini()
        session = MagicMock()
        mini_result = MagicMock()
        mini_result.scalar_one_or_none.return_value = mini

        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        # For distinct categories query
        empty_result.all.return_value = []

        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mini_result
            return empty_result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        captured: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        handlers = {t.name: t.handler for t in captured}
        result = await handlers["get_findings_by_category"](category="nonexistent")
        assert "no findings" in result.lower()

    # ── get_all_quotes ──

    @pytest.mark.asyncio
    async def test_get_all_quotes_no_quotes(self):
        mini = _make_mock_mini()
        session = _make_mock_db_session(mini)
        captured: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        handlers = {t.name: t.handler for t in captured}
        result = await handlers["get_all_quotes"]()
        assert "no quotes" in result.lower()

    @pytest.mark.asyncio
    async def test_get_all_quotes_with_quotes(self):
        from app.models.evidence import ExplorerQuote

        mini = _make_mock_mini()
        session = MagicMock()
        mini_result = MagicMock()
        mini_result.scalar_one_or_none.return_value = mini

        mock_quote = MagicMock(spec=ExplorerQuote)
        mock_quote.source_type = "github"
        mock_quote.quote = "lol no"
        mock_quote.context = "PR comment"
        mock_quote.significance = "dismissive humor"

        quotes_result = MagicMock()
        quotes_result.scalars.return_value.all.return_value = [mock_quote]

        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mini_result
            return quotes_result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        captured: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        handlers = {t.name: t.handler for t in captured}
        result = await handlers["get_all_quotes"]()
        assert "lol no" in result
        assert "PR comment" in result
        assert "dismissive humor" in result

    # ── get_explorer_summaries ──

    @pytest.mark.asyncio
    async def test_get_explorer_summaries_no_data(self):
        mini = _make_mock_mini()
        session = _make_mock_db_session(mini)
        captured: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        handlers = {t.name: t.handler for t in captured}
        result = await handlers["get_explorer_summaries"]()
        assert "no explorer data" in result.lower()

    @pytest.mark.asyncio
    async def test_get_explorer_summaries_with_data(self):
        from app.models.evidence import ExplorerFinding, ExplorerProgress

        mini = _make_mock_mini()
        mini.knowledge_graph_json = {"nodes": [{"name": "Python"}], "edges": []}
        mini.principles_json = {"principles": [{"trigger": "x", "action": "y", "value": "z"}]}

        session = MagicMock()
        mini_result = MagicMock()
        mini_result.scalar_one_or_none.return_value = mini

        mock_progress = MagicMock(spec=ExplorerProgress)
        mock_progress.source_type = "github"
        mock_progress.summary = "Analyzed 50 commits"

        progress_result = MagicMock()
        progress_result.scalars.return_value.all.return_value = [mock_progress]

        mock_finding = MagicMock(spec=ExplorerFinding)
        mock_finding.source_type = "github"
        mock_finding.category = "expertise"
        findings_result = MagicMock()
        findings_result.scalars.return_value.all.return_value = [mock_finding]

        quotes_result = MagicMock()
        quotes_result.scalars.return_value.all.return_value = []

        call_count = 0

        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mini_result
            if call_count == 2:
                return progress_result
            if call_count == 3:
                return findings_result
            return quotes_result

        session.execute = AsyncMock(side_effect=execute_side_effect)
        captured: list[AgentTool] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured.extend(tools)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        handlers = {t.name: t.handler for t in captured}
        result = await handlers["get_explorer_summaries"]()
        assert "github" in result
        assert "Analyzed 50 commits" in result
        assert "Knowledge Graph" in result
        assert "Principles" in result


# ---------------------------------------------------------------------------
# Soul document assembly
# ---------------------------------------------------------------------------


class TestSoulDocumentAssembly:
    @pytest.mark.asyncio
    async def test_identity_core_gets_you_are_prefix(self):
        """Identity Core content that doesn't start with 'You ARE' gets prefixed."""
        mini = _make_mock_mini(username="linus")
        session = _make_mock_db_session(mini)

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            # Simulate writing all sections without the 'You ARE' prefix on Identity Core
            handlers = {t.name: t.handler for t in tools}
            for section in SECTION_ORDER:
                content = (
                    f"Content for {section}"
                    if section != "Identity Core"
                    else "A kernel developer."
                )
                await handlers["write_section"](section_name=section, content=content)
            await handlers["finish"]()
            return AgentResult(final_response="done", turns_used=len(SECTION_ORDER) + 1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            result = await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        assert "You ARE linus" in result

    @pytest.mark.asyncio
    async def test_identity_core_not_double_prefixed(self):
        """If Identity Core already starts with 'You ARE', it shouldn't be duplicated."""
        mini = _make_mock_mini(username="linus")
        session = _make_mock_db_session(mini)

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            handlers = {t.name: t.handler for t in tools}
            for section in SECTION_ORDER:
                content = (
                    f"Content for {section}"
                    if section != "Identity Core"
                    else "You ARE linus. The kernel dev."
                )
                await handlers["write_section"](section_name=section, content=content)
            await handlers["finish"]()
            return AgentResult(final_response="done", turns_used=len(SECTION_ORDER) + 1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            result = await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        assert result.count("You ARE linus") == 1

    @pytest.mark.asyncio
    async def test_sections_assembled_in_order(self):
        """Sections should appear in SECTION_ORDER order in the output doc."""
        mini = _make_mock_mini(username="ada")
        session = _make_mock_db_session(mini)

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            handlers = {t.name: t.handler for t in tools}
            # Write in reverse order to test sorting
            for section in reversed(SECTION_ORDER):
                await handlers["write_section"](
                    section_name=section,
                    content=f"You ARE ada. Content for {section}.",
                )
            await handlers["finish"]()
            return AgentResult(final_response="done", turns_used=len(SECTION_ORDER) + 1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            result = await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        # Verify order by checking positions
        positions = [result.find(s) for s in SECTION_ORDER]
        assert positions == sorted(positions), "Sections not in correct order"

    @pytest.mark.asyncio
    async def test_fallback_to_final_response_when_no_sections(self):
        """If agent writes no sections, final_response is returned as soul doc."""
        mini = _make_mock_mini()
        session = _make_mock_db_session(mini)

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            # Don't call write_section at all
            return AgentResult(final_response="Fallback soul doc text", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            result = await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        assert result == "Fallback soul doc text"

    @pytest.mark.asyncio
    async def test_extra_section_included_in_output(self):
        """Sections with non-standard names should still be included."""
        mini = _make_mock_mini(username="extra")
        session = _make_mock_db_session(mini)

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            handlers = {t.name: t.handler for t in tools}
            for section in SECTION_ORDER:
                await handlers["write_section"](
                    section_name=section,
                    content=f"You ARE extra. Content for {section}.",
                )
            await handlers["write_section"](
                section_name="Custom Section",
                content="Custom content here.",
            )
            await handlers["finish"]()
            return AgentResult(final_response="done", turns_used=len(SECTION_ORDER) + 2)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            result = await run_chief_synthesizer(mini_id=mini.id, db_session=session)

        assert "Custom Section" in result
        assert "Custom content here." in result


# ---------------------------------------------------------------------------
# run_chief_synthesis — backward-compatible alias
# ---------------------------------------------------------------------------


class TestRunChiefSynthesisAlias:
    """Test the legacy run_chief_synthesis function."""

    @pytest.mark.asyncio
    async def test_alias_is_callable(self):
        """run_chief_synthesis should be an async callable."""
        import inspect

        assert inspect.iscoroutinefunction(run_chief_synthesis)

    @pytest.mark.asyncio
    async def test_alias_accepts_reports_list(self):
        """run_chief_synthesis should accept (username, reports) signature."""
        from tests.conftest import make_report

        reports = [make_report(source_name="github", personality_findings="Clean coder")]

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            handlers = {t.name: t.handler for t in tools}
            for section in SECTION_ORDER:
                await handlers["write_section"](
                    section_name=section,
                    content=f"You ARE testuser. Content for {section}.",
                )
            await handlers["finish"]()
            return AgentResult(final_response="done", turns_used=len(SECTION_ORDER) + 1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            result = await run_chief_synthesis("testuser", reports)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_alias_returns_fallback_on_no_sections(self):
        """When agent writes no sections, alias returns final_response."""
        from tests.conftest import make_report

        reports = [make_report(source_name="github")]

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            return AgentResult(final_response="Legacy fallback", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            result = await run_chief_synthesis("testuser", reports)

        assert result == "Legacy fallback"

    @pytest.mark.asyncio
    async def test_alias_includes_context_evidence_in_prompt(self):
        """Context evidence should be appended to the user prompt."""
        from tests.conftest import make_report

        reports = [make_report(source_name="github")]
        captured_prompts: list[str] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured_prompts.append(user_prompt)
            return AgentResult(final_response="done", turns_used=1)

        context_evidence = {
            "code_review": ["Great PR comment", "Another review note"],
        }

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesis("testuser", reports, context_evidence=context_evidence)

        assert len(captured_prompts) == 1
        assert "Great PR comment" in captured_prompts[0]
        assert "Code Reviews" in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_alias_includes_reports_in_prompt(self):
        """Explorer reports should appear in the user prompt."""
        from tests.conftest import make_report, make_memory

        reports = [
            make_report(
                source_name="blog",
                personality_findings="Writes long blog posts",
                memory_entries=[
                    make_memory(
                        topic="Writing",
                        content="Prefers long-form content",
                        source_type="blog",
                    )
                ],
                behavioral_quotes=[
                    {"quote": "simplicity wins", "context": "blog post", "signal_type": "value"}
                ],
            )
        ]
        captured_prompts: list[str] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            captured_prompts.append(user_prompt)
            return AgentResult(final_response="done", turns_used=1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesis("bloguser", reports)

        prompt = captured_prompts[0]
        assert "blog" in prompt
        assert "Writes long blog posts" in prompt
        assert "simplicity wins" in prompt

    @pytest.mark.asyncio
    async def test_alias_identity_core_prefix(self):
        """Legacy alias must also prefix Identity Core with 'You ARE username'."""
        from tests.conftest import make_report

        reports = [make_report(source_name="github")]

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            handlers = {t.name: t.handler for t in tools}
            for section in SECTION_ORDER:
                content = (
                    "Just a kernel dev." if section == "Identity Core" else f"Content {section}."
                )
                await handlers["write_section"](section_name=section, content=content)
            await handlers["finish"]()
            return AgentResult(final_response="done", turns_used=len(SECTION_ORDER) + 1)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            result = await run_chief_synthesis("torvalds", reports)

        assert "You ARE torvalds" in result

    @pytest.mark.asyncio
    async def test_alias_finish_not_complete_returns_not_yet(self):
        """finish tool in legacy path should reject if sections are missing."""
        from tests.conftest import make_report

        reports = [make_report(source_name="github")]
        finish_results: list[str] = []

        async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
            handlers = {t.name: t.handler for t in tools}
            # Only write one section, then call finish
            await handlers["write_section"](section_name="Identity Core", content="You ARE test.")
            result = await handlers["finish"]()
            finish_results.append(result)
            return AgentResult(final_response="done", turns_used=2)

        with patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent):
            await run_chief_synthesis("testuser", reports)

        assert len(finish_results) == 1
        assert "missing" in finish_results[0].lower() or "not yet" in finish_results[0].lower()
