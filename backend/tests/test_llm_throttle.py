"""Tests for process-wide LLM request throttling."""

from __future__ import annotations

import asyncio

import pytest

from app.core import agent as agent_module


@pytest.mark.asyncio
async def test_llm_throttle_limits_concurrency_and_kickoff_spacing(monkeypatch):
    max_concurrent = 3
    min_gap_ms = 30
    total_calls = 9
    call_duration_s = 0.06

    monkeypatch.setattr(agent_module, "_LLM_MAX_CONCURRENT_REQS", max_concurrent, raising=False)
    monkeypatch.setattr(agent_module, "_LLM_MIN_REQUEST_GAP_MS", min_gap_ms, raising=False)
    monkeypatch.setattr(
        agent_module, "_LLM_MIN_REQUEST_GAP_SECONDS", min_gap_ms / 1000.0, raising=False
    )
    monkeypatch.setattr(
        agent_module, "_LLM_REQUEST_SEMAPHORE", asyncio.Semaphore(max_concurrent), raising=False
    )
    monkeypatch.setattr(agent_module, "_LLM_REQUEST_SPACING_LOCK", asyncio.Lock(), raising=False)
    monkeypatch.setattr(agent_module, "_LLM_NEXT_REQUEST_TIME", 0.0, raising=False)

    active = 0
    max_active = 0
    kickoff_times: list[float] = []
    stats_lock = asyncio.Lock()

    async def mocked_llm_call() -> None:
        nonlocal active, max_active
        async with agent_module._llm_throttle():
            now = asyncio.get_running_loop().time()
            async with stats_lock:
                kickoff_times.append(now)
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(call_duration_s)
            async with stats_lock:
                active -= 1

    await asyncio.gather(*(mocked_llm_call() for _ in range(total_calls)))

    assert max_active <= max_concurrent
    assert len(kickoff_times) == total_calls

    ordered = sorted(kickoff_times)
    min_gap_s = min((b - a) for a, b in zip(ordered, ordered[1:], strict=False))
    assert min_gap_s >= (min_gap_ms / 1000.0) - 0.002
