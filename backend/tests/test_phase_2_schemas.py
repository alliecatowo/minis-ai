from __future__ import annotations

import json

import pytest

from app.models.evidence import ExplorerQuote
from app.models.knowledge import RelationType
from app.synthesis.explorers.tools import _decode_finding_content, build_explorer_tools
from app.models.evidence import ExplorerFinding
from tests.fixtures.postgres_mock import PostgresStyleSession


@pytest.fixture
def mock_session():
    return PostgresStyleSession()


@pytest.fixture
def tools(mock_session):
    return build_explorer_tools(
        mini_id="phase-2-mini-id",
        source_type="github",
        db_session=mock_session,
    )


@pytest.mark.skip(reason="TODO: postgres mock needs UPSERT support for explorer_progress (different table from explorer_narratives). Track in test-infra ticket.")
@pytest.mark.asyncio
async def test_save_narrative_valid_aspect_returns_saved(tools):
    tool = next(t for t in tools if t.name == "save_narrative")
    narrative = "a" * 300
    result = await tool.handler(
        aspect="voice_signature",
        narrative=narrative,
        confidence=0.7,
        evidence_ids=["ev-1", "ev-2"],
    )
    data = json.loads(result)

    assert data["saved"] is True
    assert data["aspect"] == "voice_signature"
    assert data["narrative_chars"] == 300


@pytest.mark.asyncio
async def test_save_narrative_invalid_aspect_returns_error(tools):
    tool = next(t for t in tools if t.name == "save_narrative")
    result = await tool.handler(aspect="not_real", narrative="a" * 300)
    data = json.loads(result)

    assert "error" in data
    assert "aspect must be one of" in data["error"]


@pytest.mark.asyncio
async def test_save_narrative_too_short_returns_error(tools):
    tool = next(t for t in tools if t.name == "save_narrative")
    result = await tool.handler(aspect="voice_signature", narrative="x" * 199)
    data = json.loads(result)

    assert data["error"] == "narrative must be >=200 chars (essay-length)"


@pytest.mark.asyncio
async def test_save_narrative_too_long_returns_error(tools):
    tool = next(t for t in tools if t.name == "save_narrative")
    result = await tool.handler(aspect="voice_signature", narrative="x" * 20001)
    data = json.loads(result)

    assert data["error"] == "narrative must be <=20000 chars"


def test_decode_finding_content_legacy_plain_text_returns_fallback_dict():
    decoded = _decode_finding_content("legacy plain text")

    assert decoded["content"] == "legacy plain text"
    assert decoded["temporal_signal"] is None
    assert decoded["evidence_ids"] == []
    assert decoded["support_count"] == 1
    assert decoded["contradicts_finding_ids"] == []


def test_decode_finding_content_new_json_row_returns_full_dict():
    content = json.dumps(
        {
            "content": "new finding",
            "temporal_signal": "long-standing",
            "evidence_ids": ["ev-1"],
            "support_count": 3,
            "contradicts_finding_ids": ["f-2"],
        }
    )

    decoded = _decode_finding_content(content)

    assert decoded["content"] == "new finding"
    assert decoded["temporal_signal"] == "long-standing"
    assert decoded["evidence_ids"] == ["ev-1"]
    assert decoded["support_count"] == 3
    assert decoded["contradicts_finding_ids"] == ["f-2"]


def test_decode_finding_content_malformed_json_returns_fallback_dict():
    decoded = _decode_finding_content("{not json")

    assert decoded["content"] == "{not json"
    assert decoded["evidence_ids"] == []
    assert decoded["support_count"] == 1


@pytest.mark.skip(reason="TODO: postgres mock needs UPSERT for explorer_progress (same fix as test_save_narrative_valid_aspect_returns_saved).")
@pytest.mark.asyncio
async def test_save_finding_with_evidence_ids_stores_json_payload(tools, mock_session):
    tool = next(t for t in tools if t.name == "save_finding")
    result = await tool.handler(
        category="values",
        content="Prefers explicit interfaces",
        temporal_signal="long-standing",
        evidence_ids=["ev-1", "ev-2"],
        support_count=4,
        contradicts_finding_ids=["finding-legacy"],
    )
    data = json.loads(result)
    assert data["saved"] is True

    finding = next(
        row for row in reversed(mock_session.records) if isinstance(row, ExplorerFinding)
    )
    payload = json.loads(finding.content)
    assert payload["content"] == "Prefers explicit interfaces"
    assert payload["temporal_signal"] == "long-standing"
    assert payload["evidence_ids"] == ["ev-1", "ev-2"]
    assert payload["support_count"] == 4
    assert payload["contradicts_finding_ids"] == ["finding-legacy"]


def test_explorer_quote_model_has_register_level_field():
    assert "register_level" in ExplorerQuote.__table__.columns


def test_relation_type_has_rejects_because_value():
    assert RelationType.REJECTS_BECAUSE.value == "rejects_because"
