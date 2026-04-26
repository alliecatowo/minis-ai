from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.agent import AgentResult
from app.models.evidence import ExplorerFinding, ExplorerNarrative, ExplorerQuote
from app.synthesis.chief import NARRATIVE_ASPECTS, run_chief_synthesizer
from app.synthesis.explorers.tools import build_explorer_tools


@pytest.fixture
def mock_session():
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    result.scalar_one_or_none.return_value = None
    result.scalar_one.return_value = "narrative-1"
    result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_explorer_narrative_model_persists_with_tool(mock_session):
    tools = build_explorer_tools(
        mini_id="mini-1",
        source_type="github",
        db_session=mock_session,
    )
    save_narrative = next(t for t in tools if t.name == "save_narrative")

    payload = await save_narrative.handler(
        aspect="voice_signature",
        narrative="x" * 250,
        confidence=0.7,
        evidence_ids=["ev-1"],
    )
    data = json.loads(payload)

    mock_session.execute.assert_called()
    mock_session.commit.assert_awaited()
    assert data["saved"] is True
    assert data["aspect"] == "voice_signature"
    assert data["id"] == "narrative-1"


@pytest.mark.asyncio
async def test_save_narrative_rejects_invalid_aspect(mock_session):
    tools = build_explorer_tools("mini-1", "github", mock_session)
    save_narrative = next(t for t in tools if t.name == "save_narrative")

    payload = await save_narrative.handler(aspect="invalid", narrative="x" * 250)
    data = json.loads(payload)

    assert "error" in data
    assert "aspect must be one of" in data["error"]


@pytest.mark.asyncio
async def test_save_narrative_rejects_too_short(mock_session):
    tools = build_explorer_tools("mini-1", "github", mock_session)
    save_narrative = next(t for t in tools if t.name == "save_narrative")

    payload = await save_narrative.handler(aspect="voice_signature", narrative="x" * 199)
    data = json.loads(payload)

    assert data["error"] == "narrative must be >=200 chars (essay-length)"


@pytest.mark.asyncio
async def test_save_narrative_rejects_too_long(mock_session):
    tools = build_explorer_tools("mini-1", "github", mock_session)
    save_narrative = next(t for t in tools if t.name == "save_narrative")

    payload = await save_narrative.handler(aspect="voice_signature", narrative="x" * 20001)
    data = json.loads(payload)

    assert data["error"] == "narrative must be <=20000 chars"


@pytest.mark.asyncio
async def test_save_narrative_accepts_valid_input(mock_session):
    tools = build_explorer_tools("mini-1", "github", mock_session)
    save_narrative = next(t for t in tools if t.name == "save_narrative")

    payload = await save_narrative.handler(
        aspect="architecture_worldview",
        narrative="valid narrative " * 20,
        confidence=0.8,
    )
    data = json.loads(payload)

    assert data["saved"] is True
    assert data["aspect"] == "architecture_worldview"


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeExecResult:
    def __init__(self, mini=None, rows=None):
        self._mini = mini
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._mini

    def scalars(self):
        return _FakeScalarResult(self._rows)


class _FakeFanoutSession:
    __chief_fanout__ = True

    def __init__(self, mini, findings, quotes):
        self._mini = mini
        self._findings = findings
        self._quotes = quotes
        self._narratives: list[ExplorerNarrative] = []

    def add(self, row):
        if isinstance(row, ExplorerNarrative):
            if row.created_at is None:
                row.created_at = datetime.now(timezone.utc)
            self._narratives.append(row)

    async def commit(self):
        return None

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        if entity is ExplorerFinding:
            return _FakeExecResult(rows=self._findings)
        if entity is ExplorerQuote:
            return _FakeExecResult(rows=self._quotes)
        if entity is ExplorerNarrative:
            return _FakeExecResult(rows=self._narratives)
        return _FakeExecResult(mini=self._mini)


def _sample_findings(mini_id: str) -> list[ExplorerFinding]:
    return [
        ExplorerFinding(
            mini_id=mini_id,
            source_type="github",
            category="communication_style",
            content=json.dumps({"content": "Direct in PRs, warmer in Slack"}),
            confidence=0.8,
        ),
        ExplorerFinding(
            mini_id=mini_id,
            source_type="github",
            category="values",
            content=json.dumps({"content": "Prioritizes iteration speed early"}),
            confidence=0.8,
        ),
        ExplorerFinding(
            mini_id=mini_id,
            source_type="github",
            category="architecture",
            content=json.dumps({"content": "Draws hard service boundaries around ownership"}),
            confidence=0.8,
        ),
    ]


def _sample_quotes(mini_id: str) -> list[ExplorerQuote]:
    return [
        ExplorerQuote(
            mini_id=mini_id,
            source_type="github",
            quote="This needs a clearer boundary.",
            context="PR review",
            significance="architecture worldview",
        ),
        ExplorerQuote(
            mini_id=mini_id,
            source_type="slack",
            quote="Let's keep this simple first and harden later.",
            context="incident follow-up",
            significance="decision sequencing",
        ),
    ]


@pytest.mark.skip(reason="TODO: refactor to use postgres-style session mock (sqlalchemy ON CONFLICT DO UPDATE not satisfiable by MagicMock). Tracked in lefthook+test-infra codex spike.")
@pytest.mark.asyncio
async def test_chief_fanout_loads_all_8_aspects():
    mini = SimpleNamespace(
        id="mini-fanout-1",
        username="fanout-user",
        principles_json={"principles": [{"trigger": "risk", "action": "slow down", "value": "safety"}]},
    )
    session = _FakeFanoutSession(mini, _sample_findings(mini.id), _sample_quotes(mini.id))
    seen_aspects: list[str] = []

    async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
        if tools:
            aspect = system_prompt.split("Aspect:", 1)[1].splitlines()[0].strip()
            seen_aspects.append(aspect)
            save_tool = next(t for t in tools if t.name == "save_narrative")
            await save_tool.handler(
                aspect=aspect,
                narrative=(f"Narrative for {aspect}. " * 40),
                confidence=0.72,
            )
            return AgentResult(final_response="aspect done", tool_outputs={"save_narrative": [{"aspect": aspect}]}, turns_used=1)
        return AgentResult(final_response="# IDENTITY\nSynthesized", tool_outputs={}, turns_used=1)

    factory_mock = MagicMock()
    factory_mock.return_value.__aenter__ = AsyncMock(return_value=session)
    factory_mock.return_value.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent),
        patch("app.synthesis.chief._global_session_factory", factory_mock),
    ):
        output = await run_chief_synthesizer(mini_id=mini.id, db_session=session)

    assert set(seen_aspects) == set(NARRATIVE_ASPECTS)
    assert len(seen_aspects) == len(NARRATIVE_ASPECTS)
    assert len(session._narratives) == len(NARRATIVE_ASPECTS)
    assert "# IDENTITY" in output


@pytest.mark.skip(reason="TODO: refactor to postgres-style session mock (same as test_chief_fanout_loads_all_8_aspects).")
@pytest.mark.asyncio
async def test_chief_fanout_single_aspect_failure_degrades_gracefully():
    mini = SimpleNamespace(id="mini-fanout-2", username="fanout-user", principles_json={"principles": []})
    session = _FakeFanoutSession(mini, _sample_findings(mini.id), _sample_quotes(mini.id))

    async def fake_run_agent(system_prompt, user_prompt, tools, **kwargs):
        if tools:
            aspect = system_prompt.split("Aspect:", 1)[1].splitlines()[0].strip()
            if aspect == "technical_aesthetic":
                return AgentResult(final_response=None, tool_outputs={"save_narrative": []}, turns_used=1)
            save_tool = next(t for t in tools if t.name == "save_narrative")
            await save_tool.handler(
                aspect=aspect,
                narrative=(f"Narrative for {aspect}. " * 40),
                confidence=0.66,
            )
            return AgentResult(final_response="aspect done", tool_outputs={"save_narrative": [{"aspect": aspect}]}, turns_used=1)
        return AgentResult(final_response="# IDENTITY\nSynthesized with seven narratives", tool_outputs={}, turns_used=1)

    factory_mock = MagicMock()
    factory_mock.return_value.__aenter__ = AsyncMock(return_value=session)
    factory_mock.return_value.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent),
        patch("app.synthesis.chief._global_session_factory", factory_mock),
    ):
        output = await run_chief_synthesizer(mini_id=mini.id, db_session=session)

    assert len(session._narratives) == len(NARRATIVE_ASPECTS) - 1
    assert "seven narratives" in output or "narratives" in output
