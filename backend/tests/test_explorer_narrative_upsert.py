from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql.dml import Insert as PGInsert

from app.core.agent import AgentResult
from app.models.evidence import ExplorerFinding, ExplorerNarrative, ExplorerQuote
from app.models.mini import Mini
from app.synthesis.chief import _run_chief_synthesizer_fanout


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ExecResult:
    def __init__(self, mini=None, rows=None):
        self._mini = mini
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._mini

    def scalars(self):
        return _ScalarRows(self._rows)


@pytest.mark.asyncio
async def test_chief_save_narrative_uses_upsert_for_duplicate_aspect_source():
    mini_id = "mini-upsert-1"
    mini = SimpleNamespace(id=mini_id, username="mini-user", principles_json={"principles": []})

    db_session = MagicMock()

    narrative_row = ExplorerNarrative(
        mini_id=mini_id,
        explorer_source="chief_fanout",
        aspect="values_trajectory_over_time",
        narrative="y" * 260,
        confidence=0.8,
        evidence_ids=["ev-2"],
    )

    async def execute_side_effect(stmt):
        entity = stmt.column_descriptions[0].get("entity")
        if entity is Mini:
            return _ExecResult(mini=mini)
        if entity is ExplorerFinding:
            return _ExecResult(rows=[])
        if entity is ExplorerQuote:
            return _ExecResult(rows=[])
        if entity is ExplorerNarrative:
            return _ExecResult(rows=[narrative_row])
        return _ExecResult()

    db_session.execute = AsyncMock(side_effect=execute_side_effect)

    write_exec_result = MagicMock()
    write_exec_result.scalar_one.return_value = "narrative-id"
    write_session = MagicMock()
    write_session.execute = AsyncMock(return_value=write_exec_result)
    write_session.commit = AsyncMock()

    @asynccontextmanager
    async def fake_session_cm():
        yield write_session

    def fake_session_factory():
        return fake_session_cm()

    call_index = 0

    async def fake_run_agent(system_prompt, user_prompt, tools=None, **kwargs):
        nonlocal call_index
        if tools:
            call_index += 1
            if call_index == 1:
                save_tool = next(t for t in tools if t.name == "save_narrative")
                base_narrative = "x" * 240
                await save_tool.handler(
                    aspect="values_trajectory_over_time",
                    narrative=base_narrative,
                    confidence=0.6,
                    evidence_ids=["ev-1"],
                )
                await save_tool.handler(
                    aspect="values_trajectory_over_time",
                    narrative=base_narrative + " updated",
                    confidence=0.9,
                    evidence_ids=["ev-2"],
                )
            return AgentResult(
                final_response="aspect complete",
                tool_outputs={"save_narrative": [{"saved": True}]},
                turns_used=1,
            )
        return AgentResult(final_response="# IDENTITY\nSynthesized", tool_outputs={}, turns_used=1)

    with (
        patch("app.synthesis.chief._global_session_factory", side_effect=fake_session_factory),
        patch("app.synthesis.chief.run_agent", side_effect=fake_run_agent),
    ):
        await _run_chief_synthesizer_fanout(mini_id=mini_id, db_session=db_session)

    assert write_session.execute.await_count == 2

    for call in write_session.execute.await_args_list:
        stmt = call.args[0]
        assert isinstance(stmt, PGInsert)
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT (mini_id, aspect, explorer_source) DO UPDATE" in sql
