from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.agreement_scorecard import build_agreement_scorecard_summary


def _mini(**overrides) -> SimpleNamespace:
    data = {
        "id": "mini-123",
        "username": "reviewer",
        "visibility": "public",
        "owner_id": "owner-1",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _cycle(
    predicted_approval: str,
    human_approval: str,
    predicted_blockers: list[object],
    human_blockers: list[object],
    predicted_comments: list[object],
    human_comments: list[object],
    predicted_at: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        predicted_state={
            "private_assessment": {"blocking_issues": predicted_blockers},
            "expressed_feedback": {
                "approval_state": predicted_approval,
                "comments": predicted_comments,
            },
        },
        human_review_outcome={
            "private_assessment": {"blocking_issues": human_blockers},
            "expressed_feedback": {
                "approval_state": human_approval,
                "comments": human_comments,
            },
        },
        predicted_at=predicted_at,
    )


def _session_with_mini_and_cycles(mini, cycles):
    session = AsyncMock()

    mini_result = MagicMock()
    mini_result.scalar_one_or_none.return_value = mini

    cycles_result = MagicMock()
    cycles_result.scalars.return_value.all.return_value = cycles

    session.execute = AsyncMock(side_effect=[mini_result, cycles_result])
    return session


def test_build_agreement_scorecard_summary_returns_metrics_and_trend():
    mini = _mini()
    cycles = [
        _cycle("approve", "approve", [], [], [], [], "2024-01-01T00:00:00Z"),
        _cycle(
            "request_changes",
            "request_changes",
            [{"id": "B-1"}],
            [{"id": "B-1"}],
            [{"body": "add tests"}],
            [{"body": "add tests"}],
            "2024-01-02T00:00:00Z",
        ),
        _cycle(
            "comment",
            "request_changes",
            [{"id": "B-2"}],
            [{"id": "B-3"}],
            [{"body": "consider retries"}],
            [{"body": "needs rollback plan"}],
            "2024-01-03T00:00:00Z",
        ),
        _cycle(
            "comment",
            "comment",
            [],
            [],
            [],
            [{"body": "nit: rename var"}],
            "2024-01-04T00:00:00Z",
        ),
    ]

    summary = build_agreement_scorecard_summary(mini, cycles)

    assert summary["mini_id"] == mini.id
    assert summary["username"] == mini.username
    assert summary["cycles_count"] == 4
    assert summary["approval_accuracy"] == pytest.approx(0.75)
    assert summary["blocker_precision"] == pytest.approx(0.75)
    assert summary["comment_overlap"] == pytest.approx(0.5)
    assert summary["trend"]["direction"] == "down"
    assert summary["trend"]["delta"] == pytest.approx(-2 / 3)


def test_build_agreement_scorecard_summary_handles_empty_cycles():
    summary = build_agreement_scorecard_summary(_mini(), [])

    assert summary["cycles_count"] == 0
    assert summary["approval_accuracy"] is None
    assert summary["blocker_precision"] is None
    assert summary["comment_overlap"] is None
    assert summary["trend"] == {"direction": "insufficient_data", "delta": None}


@pytest.mark.asyncio
async def test_agreement_scorecard_summary_endpoint_returns_compact_metrics(app):
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _mini()
    cycles = [
        _cycle("approve", "approve", [], [], [], [], "2024-01-01T00:00:00Z"),
        _cycle(
            "request_changes",
            "request_changes",
            [{"id": "B-1"}],
            [{"id": "B-1"}],
            [{"body": "add tests"}],
            [{"body": "add tests"}],
            "2024-01-02T00:00:00Z",
        ),
        _cycle(
            "comment",
            "request_changes",
            [{"id": "B-2"}],
            [{"id": "B-3"}],
            [{"body": "consider retries"}],
            [{"body": "needs rollback plan"}],
            "2024-01-03T00:00:00Z",
        ),
        _cycle(
            "comment",
            "comment",
            [],
            [],
            [],
            [{"body": "nit: rename var"}],
            "2024-01-04T00:00:00Z",
        ),
    ]

    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini_and_cycles(mini, cycles)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/minis/{mini.id}/agreement-scorecard-summary")

    assert response.status_code == 200
    body = response.json()
    assert body["mini_id"] == "mini-123"
    assert body["username"] == "reviewer"
    assert body["cycles_count"] == 4
    assert body["approval_accuracy"] == pytest.approx(0.75)
    assert body["blocker_precision"] == pytest.approx(0.75)
    assert body["comment_overlap"] == pytest.approx(0.5)
    assert body["trend"]["direction"] == "down"
    assert body["trend"]["delta"] == pytest.approx(-2 / 3)


@pytest.mark.asyncio
async def test_agreement_scorecard_summary_endpoint_respects_private_access(app):
    from app.core.auth import get_optional_user
    from app.db import get_session

    mini = _mini(visibility="private")
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_session] = lambda: _session_with_mini_and_cycles(mini, [])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/minis/{mini.id}/agreement-scorecard-summary")

    assert response.status_code == 404
