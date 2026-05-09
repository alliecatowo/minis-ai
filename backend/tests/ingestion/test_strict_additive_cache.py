"""Tests for W4.2 strict additive cache (get_latest_evidence_with_hashes + pipeline wiring).

Uses an in-memory SQLite database — no real PostgreSQL connection required.
Three canonical cases:
  1. Re-run with no upstream changes → 0 inserts, 0 updates, all rows skipped.
  2. Re-run with changed content (same external_id, different hash) → 1 insert + 1 superseded.
  3. Re-run with new item (new external_id) → 1 insert.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ingestion.delta import get_latest_evidence_with_hashes
from app.ingestion.hashing import hash_evidence_content
from app.models.evidence import Evidence


# ---------------------------------------------------------------------------
# SQLite schema (mirrors delta test pattern)
# ---------------------------------------------------------------------------

_CREATE_EVIDENCE = """
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    item_type TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT,
    source_privacy TEXT NOT NULL DEFAULT 'public',
    retention_policy TEXT,
    retention_expires_at TEXT,
    source_authorization TEXT,
    authorization_revoked_at TEXT,
    access_classification TEXT,
    lifecycle_audit_json TEXT,
    source_uri TEXT,
    author_id TEXT,
    audience_id TEXT,
    target_id TEXT,
    scope_json TEXT,
    raw_body TEXT,
    raw_body_ref TEXT,
    raw_context_json TEXT,
    provenance_json TEXT,
    explored INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    external_id TEXT,
    evidence_date TEXT,
    last_fetched_at TEXT,
    content_hash TEXT,
    superseded_at TEXT,
    superseded_by_evidence_id TEXT,
    supersession_reason_code TEXT,
    supersession_reason_json TEXT,
    ai_contamination_score REAL,
    ai_contamination_confidence REAL,
    ai_contamination_status TEXT,
    ai_contamination_reasoning TEXT,
    ai_contamination_provenance_json TEXT,
    ai_contamination_checked_at TEXT,
    ai_authorship_likelihood REAL,
    ai_style_markers TEXT,
    context TEXT NOT NULL DEFAULT 'general'
)
"""

_CREATE_IDX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_mini_source_external_id
ON evidence (mini_id, source_type, external_id)
WHERE external_id IS NOT NULL AND superseded_at IS NULL
"""


@pytest.fixture(scope="module")
def engine():
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest_asyncio.fixture(scope="module")
async def tables(engine):
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_EVIDENCE))
        await conn.execute(text(_CREATE_IDX))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS evidence"))


@pytest_asyncio.fixture
async def session(engine, tables):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
        await s.rollback()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(
    mini_id: str,
    source_type: str = "github",
    external_id: str | None = None,
    content: str = "hello world",
    content_hash: str | None = None,
    superseded_at: datetime | None = None,
) -> Evidence:
    return Evidence(
        id=str(uuid.uuid4()),
        mini_id=mini_id,
        source_type=source_type,
        item_type="commit",
        content=content,
        external_id=external_id,
        content_hash=content_hash or hash_evidence_content(content),
        superseded_at=superseded_at,
        last_fetched_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# get_latest_evidence_with_hashes
# ---------------------------------------------------------------------------


class TestGetLatestEvidenceWithHashes:
    @pytest.mark.asyncio
    async def test_returns_active_rows_only(self, session: AsyncSession):
        mini_id = str(uuid.uuid4())
        content = "commit content"
        h = hash_evidence_content(content)
        session.add(_make_evidence(mini_id, external_id="sha-1", content=content, content_hash=h))
        # superseded row should be excluded
        session.add(
            _make_evidence(
                mini_id,
                external_id="sha-2",
                content="old content",
                superseded_at=datetime.now(timezone.utc),
            )
        )
        await session.flush()

        result = await get_latest_evidence_with_hashes(session, mini_id, "github")
        assert result == {"sha-1": h}

    @pytest.mark.asyncio
    async def test_excludes_null_external_id(self, session: AsyncSession):
        mini_id = str(uuid.uuid4())
        session.add(_make_evidence(mini_id, external_id=None, content="no id"))
        await session.flush()

        result = await get_latest_evidence_with_hashes(session, mini_id, "github")
        assert result == {}

    @pytest.mark.asyncio
    async def test_scoped_to_mini_and_source(self, session: AsyncSession):
        mini_a = str(uuid.uuid4())
        mini_b = str(uuid.uuid4())
        content_a = "content a"
        content_b = "content b"
        session.add(_make_evidence(mini_a, source_type="github", external_id="gh-1", content=content_a))
        session.add(_make_evidence(mini_b, source_type="github", external_id="gh-2", content=content_b))
        session.add(_make_evidence(mini_a, source_type="claude_code", external_id="cc-1", content="cc"))
        await session.flush()

        result = await get_latest_evidence_with_hashes(session, mini_a, "github")
        assert set(result.keys()) == {"gh-1"}
        assert result["gh-1"] == hash_evidence_content(content_a)

    @pytest.mark.asyncio
    async def test_empty_when_no_rows(self, session: AsyncSession):
        mini_id = str(uuid.uuid4())
        result = await get_latest_evidence_with_hashes(session, mini_id, "github")
        assert result == {}


# ---------------------------------------------------------------------------
# _store_evidence_items_in_db integration — strict cache behaviour
# ---------------------------------------------------------------------------
# We test `_store_evidence_items_in_db` directly using mocked session_factory
# so we can verify the 3 canonical cache cases without a full pipeline.


def _make_evidence_item(
    external_id: str,
    content: str,
    source_type: str = "github",
) -> MagicMock:
    """Build a minimal EvidenceItem-like mock."""
    item = MagicMock()
    item.external_id = external_id
    item.source_type = source_type
    item.item_type = "commit"
    item.content = content
    item.context = "general"
    item.metadata = {}
    item.privacy = "public"
    item.retention_policy = None
    item.retention_expires_at = None
    item.source_authorization = None
    item.authorization_revoked_at = None
    item.access_classification = None
    item.lifecycle_audit = None
    item.source_uri = None
    item.author_id = None
    item.audience_id = None
    item.target_id = None
    item.scope = None
    item.raw_body = None
    item.raw_body_ref = None
    item.raw_context = None
    item.provenance = None
    item.evidence_date = None
    return item


class TestStoreEvidenceStrictCache:
    """Test _store_evidence_items_in_db with pre-loaded existing_hashes."""

    @pytest.mark.asyncio
    async def test_no_upstream_changes_all_skipped(self):
        """Case 1: all items already in DB with matching hash → 0 inserts, 0 updates, all skipped."""
        from app.synthesis.pipeline import _store_evidence_items_in_db

        content = "unchanged commit message"
        h = hash_evidence_content(content, metadata={"_context": "general"})
        items = [_make_evidence_item("sha-abc", content)]
        existing_hashes = {"sha-abc": h}

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)
        session_mock.begin = MagicMock(return_value=session_mock)
        session_mock.add = MagicMock()
        session_mock.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        session_factory = MagicMock(return_value=session_mock)

        with patch("app.synthesis.pipeline.score_ai_authorship", return_value=(0.0, {})), \
             patch("app.synthesis.pipeline.score_evidence_batch", new_callable=AsyncMock):
            inserted, updated, skipped = await _store_evidence_items_in_db(
                mini_id="mini-1",
                source_name="github",
                items=items,
                session_factory=session_factory,
                existing_hashes=existing_hashes,
            )

        assert inserted == 0
        assert updated == 0
        assert skipped == 1

    @pytest.mark.asyncio
    async def test_changed_content_produces_supersession(self):
        """Case 2: same external_id but different hash → 1 insert + 1 superseded."""
        from app.synthesis.pipeline import _store_evidence_items_in_db

        old_content = "old commit"
        new_content = "updated commit"
        old_hash = hash_evidence_content(old_content, metadata={"_context": "general"})
        items = [_make_evidence_item("sha-abc", new_content)]
        # existing_hashes has the OLD hash so this item should NOT be skipped
        existing_hashes = {"sha-abc": old_hash}

        existing_row = MagicMock()
        existing_row.content_hash = old_hash
        existing_row.id = "old-evidence-id"

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)
        session_mock.begin = MagicMock(return_value=session_mock)
        session_mock.add = MagicMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none = MagicMock(return_value=existing_row)
        session_mock.execute = AsyncMock(return_value=execute_result)
        session_factory = MagicMock(return_value=session_mock)

        with patch("app.synthesis.pipeline.score_ai_authorship", return_value=(0.0, {})), \
             patch("app.synthesis.pipeline.score_evidence_batch", new_callable=AsyncMock):
            inserted, updated, skipped = await _store_evidence_items_in_db(
                mini_id="mini-1",
                source_name="github",
                items=items,
                session_factory=session_factory,
                existing_hashes=existing_hashes,
            )

        # 1 new row inserted, 1 superseded (updated), 0 skipped
        assert inserted == 1
        assert updated == 1
        assert skipped == 0
        # The existing row should have been marked superseded
        assert existing_row.superseded_at is not None
        assert existing_row.supersession_reason_code == "content_hash_changed"

    @pytest.mark.asyncio
    async def test_new_external_id_produces_insert(self):
        """Case 3: new external_id not in existing_hashes → 1 insert."""
        from app.synthesis.pipeline import _store_evidence_items_in_db

        content = "brand new commit"
        items = [_make_evidence_item("sha-new", content)]
        existing_hashes: dict[str, str] = {}  # nothing pre-loaded

        session_mock = AsyncMock()
        session_mock.__aenter__ = AsyncMock(return_value=session_mock)
        session_mock.__aexit__ = AsyncMock(return_value=False)
        session_mock.begin = MagicMock(return_value=session_mock)
        session_mock.add = MagicMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none = MagicMock(return_value=None)
        session_mock.execute = AsyncMock(return_value=execute_result)
        session_factory = MagicMock(return_value=session_mock)

        with patch("app.synthesis.pipeline.score_ai_authorship", return_value=(0.0, {})), \
             patch("app.synthesis.pipeline.score_evidence_batch", new_callable=AsyncMock):
            inserted, updated, skipped = await _store_evidence_items_in_db(
                mini_id="mini-1",
                source_name="github",
                items=items,
                session_factory=session_factory,
                existing_hashes=existing_hashes,
            )

        assert inserted == 1
        assert updated == 0
        assert skipped == 0
        # Verify session.add was called (new row persisted)
        session_mock.add.assert_called()
