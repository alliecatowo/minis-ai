"""Tests for the review outcomes ingestion source."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import ReviewCycle
from app.plugins.sources.review_outcomes import ReviewOutcomesSource


class TestReviewOutcomesSource:
    def test_implements_ingestion_source(self):
        from app.plugins.base import IngestionSource
        assert isinstance(ReviewOutcomesSource(), IngestionSource)

    def test_name(self):
        assert ReviewOutcomesSource.name == "review_outcomes"

    @pytest.mark.asyncio
    async def test_fetch_items(self):
        source = ReviewOutcomesSource()
        mini_id = "test-mini-id"
        
        # Mock ReviewCycle records
        cycle1 = ReviewCycle(
            id="cycle-1",
            mini_id=mini_id,
            source_type="github",
            external_id="pr:123",
            predicted_state={
                "expressed_feedback": {
                    "approval_state": "approved",
                    "summary": "Looks good!"
                }
            },
            human_review_outcome={
                "expressed_feedback": {
                    "approval_state": "commented",
                    "summary": "Actually, I have some nits."
                }
            },
            delta_metrics={"approval_state_changed": True},
            human_reviewed_at=None,
            updated_at=None
        )
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [cycle1]
        
        session = MagicMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=mock_result)
        
        items = []
        async for item in source.fetch_items("test-user", mini_id, session):
            items.append(item)
            
        assert len(items) == 1
        item = items[0]
        assert item.external_id == "review_outcome:cycle-1"
        assert "Predicted Approval: approved" in item.content
        assert "Human did: commented" in item.content
        assert "Actually, I have some nits." in item.content
        assert "Delta: {'approval_state_changed': True}" in item.content
        assert item.context == "code_review"

    @pytest.mark.asyncio
    async def test_fetch_items_skips_since(self):
        source = ReviewOutcomesSource()
        mini_id = "test-mini-id"
        
        cycle1 = ReviewCycle(id="cycle-1", human_review_outcome={"foo": "bar"})
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [cycle1]
        
        session = MagicMock(spec=AsyncSession)
        session.execute = AsyncMock(return_value=mock_result)
        
        # Already saw cycle-1
        since = {"review_outcome:cycle-1"}
        
        items = []
        async for item in source.fetch_items("test-user", mini_id, session, since_external_ids=since):
            items.append(item)
            
        assert len(items) == 0
