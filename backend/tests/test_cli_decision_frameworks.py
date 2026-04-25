"""Tests for the `decision-frameworks` CLI subcommand.

Uses Typer's CliRunner and a monkeypatched async_session so no real DB is needed.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from typer.testing import CliRunner

import cli as minis_cli


runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FRAMEWORK_HIGH = {
    "framework_id": "fw-readability",
    "condition": "code review with poor naming",
    "decision_order": ["request rename"],
    "value_ids": ["value:readability"],
    "confidence": 0.85,
    "revision": 3,
}

_FRAMEWORK_MID = {
    "framework_id": "fw-tests",
    "condition": "new public API without tests",
    "decision_order": ["block until covered"],
    "value_ids": ["value:correctness"],
    "confidence": 0.55,
    "revision": 1,
}

_FRAMEWORK_LOW = {
    "framework_id": "fw-style",
    "condition": "minor style nit",
    "decision_order": ["leave comment"],
    "value_ids": ["value:consistency"],
    "confidence": 0.20,
    "revision": 0,
}


def _make_mini(
    username: str = "testdev",
    principles_json: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="mini-abc123",
        username=username,
        principles_json=principles_json,
    )


def _mock_session(mini: SimpleNamespace | None) -> MagicMock:
    """Return an async context-manager mock that yields a session returning *mini*."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = mini
    session.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def _ctx():
        yield session

    mock = MagicMock()
    mock.return_value = _ctx()
    return mock


def _invoke(args: list[str], monkeypatch, mini: SimpleNamespace | None):
    monkeypatch.setattr(minis_cli, "async_session", _mock_session(mini))
    return runner.invoke(minis_cli.app, ["decision-frameworks", *args])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path_shows_all_frameworks(monkeypatch):
    mini = _make_mini(
        principles_json={
            "frameworks": [_FRAMEWORK_HIGH, _FRAMEWORK_MID, _FRAMEWORK_LOW]
        }
    )
    result = _invoke(["testdev"], monkeypatch, mini)

    assert result.exit_code == 0, result.output
    assert "fw-readability" in result.output
    assert "fw-tests" in result.output
    assert "fw-style" in result.output
    # Summary line
    assert "3" in result.output  # 3 frameworks shown
    # High-confidence badge
    assert "HIGH CONFIDENCE" in result.output
    # fw-readability has revision=3 — the Rev column shows the number
    assert "│   3 │" in result.output
    # Low-confidence badge
    assert "LOW CONFIDENCE" in result.output


def test_mini_not_found_exits_nonzero(monkeypatch):
    result = _invoke(["nobody"], monkeypatch, None)

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_no_frameworks_on_mini_exits_nonzero(monkeypatch):
    mini = _make_mini(principles_json=None)
    result = _invoke(["testdev"], monkeypatch, mini)

    assert result.exit_code == 1
    assert "No decision frameworks" in result.output


def test_no_frameworks_empty_dict(monkeypatch):
    mini = _make_mini(principles_json={})
    result = _invoke(["testdev"], monkeypatch, mini)

    assert result.exit_code == 1
    assert "No decision frameworks" in result.output


def test_min_confidence_filter_excludes_low(monkeypatch):
    mini = _make_mini(
        principles_json={
            "frameworks": [_FRAMEWORK_HIGH, _FRAMEWORK_MID, _FRAMEWORK_LOW]
        }
    )
    result = _invoke(["testdev", "--min-confidence", "0.5"], monkeypatch, mini)

    assert result.exit_code == 0, result.output
    assert "fw-readability" in result.output
    assert "fw-tests" in result.output
    # fw-style has confidence 0.20, below threshold
    assert "fw-style" not in result.output


def test_min_confidence_filter_excludes_all_exits_nonzero(monkeypatch):
    mini = _make_mini(
        principles_json={
            "frameworks": [_FRAMEWORK_LOW]
        }
    )
    result = _invoke(["testdev", "--min-confidence", "0.9"], monkeypatch, mini)

    assert result.exit_code == 1
    assert "min-confidence" in result.output


def test_limit_caps_output(monkeypatch):
    mini = _make_mini(
        principles_json={
            "frameworks": [_FRAMEWORK_HIGH, _FRAMEWORK_MID, _FRAMEWORK_LOW]
        }
    )
    result = _invoke(["testdev", "--limit", "1"], monkeypatch, mini)

    assert result.exit_code == 0, result.output
    # Only the highest-confidence framework should appear
    assert "fw-readability" in result.output
    assert "fw-tests" not in result.output
    assert "fw-style" not in result.output


def test_frameworks_sorted_by_confidence_desc(monkeypatch):
    mini = _make_mini(
        principles_json={
            "frameworks": [_FRAMEWORK_LOW, _FRAMEWORK_MID, _FRAMEWORK_HIGH]
        }
    )
    result = _invoke(["testdev"], monkeypatch, mini)

    assert result.exit_code == 0, result.output
    # Verify ordering: fw-readability (0.85) appears before fw-tests (0.55)
    high_pos = result.output.find("fw-readability")
    mid_pos = result.output.find("fw-tests")
    assert high_pos < mid_pos


def test_revision_validated_badge_singular(monkeypatch):
    fw_one_rev = {**_FRAMEWORK_MID, "revision": 1, "framework_id": "fw-one-rev"}
    mini = _make_mini(principles_json={"frameworks": [fw_one_rev]})
    result = _invoke(["testdev"], monkeypatch, mini)

    assert result.exit_code == 0, result.output
    # revision=1 shows in the Rev column
    assert "│   1 │" in result.output
    # The module-level badge helper produces singular form
    badge = minis_cli._confidence_badge(0.55, 1)
    assert "validated 1 time" in badge
    assert "validated 1 times" not in badge


def test_summary_shows_mean_confidence_and_max_revision(monkeypatch):
    mini = _make_mini(
        principles_json={
            "frameworks": [_FRAMEWORK_HIGH, _FRAMEWORK_MID]
        }
    )
    result = _invoke(["testdev"], monkeypatch, mini)

    assert result.exit_code == 0, result.output
    # Mean of 0.85 and 0.55 = 0.70 → rendered as "70%"
    assert "70%" in result.output
    # Max revision is 3
    assert "3" in result.output
