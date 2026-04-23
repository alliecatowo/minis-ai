"""Tests for source expansion logic in the pipeline."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.evidence import ReviewCycle
from app.synthesis.pipeline import run_pipeline


class TestPipelineSourceExpansion:
    def _make_session_factory(self, review_cycles=None):
        mock_session = MagicMock()
        
        # MiniRepoConfig query
        cfg_result = MagicMock()
        cfg_result.scalars.return_value.all.return_value = []
        
        # ReviewCycle query
        review_result = MagicMock()
        review_result.scalar_one_or_none.return_value = review_cycles[0] if review_cycles else None
        
        # Track calls
        call_count = 0
        async def execute_side_effect(stmt):
            nonlocal call_count
            call_count += 1
            if "minirepoconfig" in str(stmt).lower():
                return cfg_result
            if "review_cycles" in str(stmt).lower():
                return review_result
            return MagicMock()

        mock_session.execute = AsyncMock(side_effect=execute_side_effect)

        @asynccontextmanager
        async def factory():
            yield mock_session
            
        return factory

    @pytest.mark.asyncio
    async def test_auto_expansion_excludes_review_outcomes_when_no_records(self):
        # We need to mock registry.list_sources to include review_outcomes
        with (
            patch("app.synthesis.pipeline.registry") as mock_registry,
            patch("app.synthesis.pipeline.get_explorer", side_effect=KeyError("skip")),
            patch("app.synthesis.pipeline.logger") as mock_logger
        ):
            mock_registry.list_sources.return_value = ["github", "review_outcomes"]
            
            # session_factory returns None for ReviewCycle query
            session_factory = self._make_session_factory(review_cycles=[])
            
            # We expect run_pipeline to fail later because we're skipping everything, 
            # but we want to check what it logged for source_names expansion.
            try:
                await run_pipeline(
                    username="testuser",
                    session_factory=session_factory,
                    mini_id="test-mini",
                    sources=None # Trigger auto-expansion
                )
            except ValueError: # Expected if no sources remain or fail
                pass
                
            # Check logger.info call for expanded sources
            expansion_log = [
                call for call in mock_logger.info.call_args_list 
                if "auto-expanding sources" in str(call)
            ]
            assert len(expansion_log) > 0
            # Should NOT contain review_outcomes
            sources_logged = expansion_log[0][0][1]
            assert "github" in sources_logged
            assert "review_outcomes" not in sources_logged

    @pytest.mark.asyncio
    async def test_auto_expansion_includes_review_outcomes_when_records_exist(self):
        with (
            patch("app.synthesis.pipeline.registry") as mock_registry,
            patch("app.synthesis.pipeline.get_explorer", side_effect=KeyError("skip")),
            patch("app.synthesis.pipeline.logger") as mock_logger
        ):
            mock_registry.list_sources.return_value = ["github", "review_outcomes"]
            
            # session_factory returns a ReviewCycle record
            session_factory = self._make_session_factory(review_cycles=[ReviewCycle(id="1")])
            
            try:
                await run_pipeline(
                    username="testuser",
                    session_factory=session_factory,
                    mini_id="test-mini",
                    sources=None # Trigger auto-expansion
                )
            except ValueError:
                pass
                
            expansion_log = [
                call for call in mock_logger.info.call_args_list 
                if "auto-expanding sources" in str(call)
            ]
            assert len(expansion_log) > 0
            # Should contain review_outcomes
            sources_logged = expansion_log[0][0][1]
            assert "github" in sources_logged
            assert "review_outcomes" in sources_logged
