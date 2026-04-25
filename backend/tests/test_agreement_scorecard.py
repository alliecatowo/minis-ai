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
            [{"key": "B-1"}],
            [{"key": "B-1"}],
            [{"summary": "add tests"}],
            [{"summary": "add tests", "rationale": "missing test coverage"}],
            "2024-01-02T00:00:00Z",
        ),
        _cycle(
            "comment",
            "request_changes",
            [{"key": "B-2"}],
            [{"key": "B-3"}],
            [{"summary": "consider retries"}],
            [{"summary": "needs rollback plan", "rationale": "operability risk"}],
            "2024-01-03T00:00:00Z",
        ),
        _cycle(
            "comment",
            "comment",
            [],
            [],
            [],
            [{"summary": "nit: rename var"}],
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


def test_build_agreement_scorecard_summary_supports_legacy_blocker_and_comment_fields():
    mini = _mini()
    cycles = [
        _cycle(
            "comment",
            "comment",
            [{"id": "B-legacy"}],
            [{"id": "B-legacy"}],
            [{"body": "legacy blocker reason"}],
            [{"body": "legacy blocker reason"}],
            "2024-01-01T00:00:00Z",
        )
    ]

    summary = build_agreement_scorecard_summary(mini, cycles)

    assert summary["cycles_count"] == 1
    assert summary["blocker_precision"] == pytest.approx(1.0)
    assert summary["blocker_recall"] == pytest.approx(1.0)
    assert summary["comment_overlap"] == pytest.approx(1.0)


def test_build_agreement_scorecard_summary_handles_empty_cycles():
    summary = build_agreement_scorecard_summary(_mini(), [])

    assert summary["cycles_count"] == 0
    assert summary["approval_accuracy"] is None
    assert summary["blocker_precision"] is None
    assert summary["comment_overlap"] is None
    assert summary["trend"] == {"direction": "insufficient_data", "delta": None}


@pytest.mark.asyncio
async def test_agreement_scorecard_summary_endpoint_returns_compact_metrics_for_owner(
    app,
    mock_user,
):
    from app.core.auth import get_current_user
    from app.db import get_session

    mini = _mini(owner_id=mock_user.id)
    cycles = [
        _cycle("approve", "approve", [], [], [], [], "2024-01-01T00:00:00Z"),
        _cycle(
            "request_changes",
            "request_changes",
            [{"key": "B-1"}],
            [{"key": "B-1"}],
            [{"summary": "add tests"}],
            [{"summary": "add tests", "rationale": "risk reduction"}],
            "2024-01-02T00:00:00Z",
        ),
        _cycle(
            "comment",
            "request_changes",
            [{"key": "B-2"}],
            [{"key": "B-3"}],
            [{"summary": "consider retries"}],
            [{"summary": "needs rollback plan", "rationale": "release concern"}],
            "2024-01-03T00:00:00Z",
        ),
        _cycle(
            "comment",
            "comment",
            [],
            [],
            [],
            [{"summary": "nit: rename var"}],
            "2024-01-04T00:00:00Z",
        ),
    ]

    app.dependency_overrides[get_current_user] = lambda: mock_user
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
async def test_agreement_scorecard_summary_endpoint_requires_authentication(app):
    from app.db import get_session

    mini = _mini()
    app.dependency_overrides[get_session] = lambda: _session_with_mini_and_cycles(mini, [])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/minis/{mini.id}/agreement-scorecard-summary")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_agreement_scorecard_summary_endpoint_rejects_non_owner(app, mock_user):
    from app.core.auth import get_current_user
    from app.db import get_session

    mini = _mini(owner_id="someone-else")
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_session] = lambda: _session_with_mini_and_cycles(mini, [])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/minis/{mini.id}/agreement-scorecard-summary")

    assert response.status_code == 403
