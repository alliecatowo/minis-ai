from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.mini import Mini
from app.plugins.base import EvidenceItem
from app.synthesis.explorers.base import ExplorerReport
from app.synthesis.pipeline import run_pipeline_with_events


class _MockScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _MockResult:
    def __init__(self, *, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = list(rows or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        if self._scalar is None:
            raise ValueError("No rows returned")
        return self._scalar

    def scalars(self):
        return _MockScalars(self._rows)


class _BeginCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return None


@dataclass
class _SessionRecorder:
    mini: Mini

    def __post_init__(self):
        self.executed = []

    def begin(self):
        return _BeginCtx()

    async def execute(self, stmt):
        self.executed.append(stmt)
        stmt_name = stmt.__class__.__name__.lower()
        if "delete" in stmt_name:
            return _MockResult()

        if hasattr(stmt, "column_descriptions"):
            entity = stmt.column_descriptions[0].get("entity")
            if entity is Mini:
                return _MockResult(scalar=self.mini, rows=[self.mini])
            return _MockResult(rows=[])

        return _MockResult()

    def add(self, _record):
        return None


class _FakeSource:
    async def fetch_items(self, identifier, mini_id, session, *, since_external_ids=None):
        del identifier, mini_id, session, since_external_ids
        yield EvidenceItem(
            external_id="item-1",
            source_type="github",
            item_type="review",
            content="example evidence",
            evidence_date=datetime.now(),
        )


class _FakeExplorer:
    source_name = "github"

    async def explore(self, username, evidence, raw_data):
        del username, evidence, raw_data
        return ExplorerReport(source_name="github", personality_findings="ok")


@asynccontextmanager
async def _session_factory(recorder: _SessionRecorder):
    yield recorder


async def _run_with_freshness_mode(mode: str):
    mini = Mini(id="mini-1", username="testuser", status="processing")
    recorder = _SessionRecorder(mini=mini)

    with (
        patch("app.synthesis.pipeline.get_latest_external_ids", new=AsyncMock(return_value=set())),
        patch(
            "app.synthesis.pipeline._store_evidence_items_in_db",
            new=AsyncMock(return_value=(1, 0)),
        ),
        patch(
            "app.synthesis.pipeline._build_usable_evidence_text",
            new=AsyncMock(return_value="evidence"),
        ),
        patch("app.synthesis.pipeline.get_explorer", return_value=_FakeExplorer()),
        patch("app.synthesis.pipeline.run_chief_synthesizer", new=AsyncMock(return_value="spirit")),
        patch(
            "app.synthesis.pipeline._build_structured_from_db",
            new=AsyncMock(return_value=({"nodes": [], "edges": []}, {"principles": []})),
        ),
        patch(
            "app.synthesis.pipeline._build_synthetic_reports_from_db",
            new=AsyncMock(return_value=[]),
        ),
        patch("app.synthesis.pipeline.build_system_prompt", return_value="system prompt"),
        patch("app.synthesis.pipeline._generate_embeddings", new=AsyncMock(return_value=None)),
        patch("app.synthesis.pipeline.registry.get_source", return_value=_FakeSource()),
        patch("app.synthesis.memory_assembler.extract_values_json", return_value={}),
        patch("app.synthesis.memory_assembler.extract_roles_llm", new=AsyncMock(return_value={})),
        patch("app.synthesis.memory_assembler.extract_skills_llm", new=AsyncMock(return_value={})),
        patch("app.synthesis.memory_assembler.extract_traits_llm", new=AsyncMock(return_value={})),
        patch(
            "app.synthesis.decision_frameworks.attach_decision_frameworks",
            side_effect=lambda principles_json, _motivation: principles_json,
        ),
        patch("app.synthesis.personality.infer_personality_typology", new=AsyncMock(return_value=None)),
        patch(
            "app.synthesis.behavioral_context.infer_behavioral_context",
            new=AsyncMock(return_value=None),
        ),
        patch("app.synthesis.motivations.infer_motivations", new=AsyncMock(return_value=None)),
    ):
        await run_pipeline_with_events(
            username="testuser",
            session_factory=lambda: _session_factory(recorder),
            sources=["github"],
            mini_id="mini-1",
            freshness_mode=mode,
        )

    deleted_tables = {
        stmt.table.name for stmt in recorder.executed if "delete" in stmt.__class__.__name__.lower()
    }
    return deleted_tables


@pytest.mark.asyncio
async def test_run_pipeline_with_events_replace_wipes_explorer_outputs_before_rebuild():
    deleted_tables = await _run_with_freshness_mode("replace")

    assert "explorer_findings" in deleted_tables
    assert "explorer_quotes" in deleted_tables
    assert "explorer_narratives" in deleted_tables
    assert "explorer_progress" in deleted_tables
    assert "evidence" not in deleted_tables


@pytest.mark.asyncio
async def test_run_pipeline_with_events_append_does_not_wipe_explorer_outputs():
    deleted_tables = await _run_with_freshness_mode("append")

    assert "explorer_findings" not in deleted_tables
    assert "explorer_quotes" not in deleted_tables
    assert "explorer_narratives" not in deleted_tables
    assert "explorer_progress" not in deleted_tables
    assert "evidence" not in deleted_tables
