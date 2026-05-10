"""Tests for default source selection in the pipeline.

The pipeline used to auto-expand `sources=None` to *every* registered
explorer (github, claude_code, blog, hackernews, stackoverflow, devto,
website, review_outcomes...). That burned tokens on noisy / absent sources
for users who only have github + claude_code signal. We now default to
those two sources only; callers who want a wider net pass them in.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.synthesis.pipeline import run_pipeline


def _session_factory():
    mock_session = MagicMock()

    cfg_result = MagicMock()
    cfg_result.scalars.return_value.all.return_value = []

    async def execute_side_effect(stmt):
        if "minirepoconfig" in str(stmt).lower():
            return cfg_result
        return MagicMock()

    mock_session.execute = AsyncMock(side_effect=execute_side_effect)

    @asynccontextmanager
    async def factory():
        yield mock_session

    return factory


async def _attempted_source_names(*, sources, registered):
    """Run the pipeline far enough that source-iteration starts, then return
    the ordered list of sources the pipeline asked the registry to resolve.

    The pipeline halts at the first KeyError from `registry.get_source`, so
    we observe at most one call per run — but the *first* call already tells
    us whether the default-source resolution put the right source first.
    """
    with (
        patch("app.synthesis.pipeline.registry") as mock_registry,
        patch("app.synthesis.pipeline.get_explorer", side_effect=KeyError("skip")),
    ):
        mock_registry.list_sources.return_value = list(registered)
        mock_registry.get_source.side_effect = KeyError("unmocked source")
        try:
            await run_pipeline(
                username="testuser",
                session_factory=_session_factory(),
                mini_id="test-mini",
                sources=sources,
            )
        except Exception:
            pass
        return [c.args[0] for c in mock_registry.get_source.call_args_list]


@pytest.mark.asyncio
async def test_default_picks_github_first_when_both_registered():
    calls = await _attempted_source_names(
        sources=None,
        registered=[
            "github",
            "claude_code",
            "blog",
            "hackernews",
            "stackoverflow",
            "devto",
            "website",
            "review_outcomes",
        ],
    )
    assert calls[:1] == ["github"]
    # Auto-expansion is gone, so noise sources must not appear.
    for noise in ("blog", "hackernews", "stackoverflow", "devto", "website", "review_outcomes"):
        assert noise not in calls


@pytest.mark.asyncio
async def test_default_falls_back_to_github_when_claude_code_missing():
    calls = await _attempted_source_names(
        sources=None,
        registered=["github", "blog"],
    )
    assert calls[:1] == ["github"]
    assert "blog" not in calls


@pytest.mark.asyncio
async def test_explicit_sources_are_honored_first():
    calls = await _attempted_source_names(
        sources=["blog", "review_outcomes"],
        registered=["github", "blog", "review_outcomes"],
    )
    assert calls[:1] == ["blog"]
