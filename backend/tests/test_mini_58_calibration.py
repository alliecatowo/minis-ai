"""Tests for MINI-58: prediction feedback as first-class product memory.

Covers:
- Precision/recall computation logic (via calculate_metrics helper)
- build_calibration_note output for various cycle counts
- Calibration note injection in _build_predictor_system_prompt
- GET /api/minis/by-username/{username}/feedback-memory route
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _cycle(
    predicted_approval: str,
    human_approval: str,
    predicted_blockers: list,
    human_blockers: list,
    human_review_outcome: dict | None = None,
) -> SimpleNamespace:
    """Build a minimal ReviewCycle-like namespace for testing."""
    outcome = human_review_outcome or {
        "private_assessment": {"blocking_issues": human_blockers},
        "expressed_feedback": {
            "approval_state": human_approval,
            "comments": [],
        },
    }
    return SimpleNamespace(
        predicted_state={
            "private_assessment": {"blocking_issues": predicted_blockers},
            "expressed_feedback": {
                "approval_state": predicted_approval,
                "comments": [],
            },
        },
        human_review_outcome=outcome,
        predicted_at="2026-01-01T00:00:00Z",
        human_reviewed_at="2026-01-02T00:00:00Z",
    )


def _mini(**overrides) -> SimpleNamespace:
    data = {
        "id": "mini-abc",
        "username": "reviewer",
        "display_name": "Reviewer",
        "avatar_url": None,
        "owner_id": "owner-1",
        "visibility": "public",
        "org_id": None,
        "bio": None,
        "spirit_content": "A rigorous reviewer.",
        "memory_content": "Values correctness.",
        "system_prompt": "# IDENTITY\nYou are reviewer.",
        "principles_json": None,
        "personality_typology_json": None,
        "behavioral_context_json": None,
        "motivations_json": None,
        "status": "ready",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


# ── precision/recall computation ──────────────────────────────────────────────

class TestCalculateMetricsPrecisionRecall:
    """Verify the shared calculate_metrics helper computes precision/recall correctly."""

    def test_perfect_match(self):
        from scripts.calculate_review_agreement import calculate_metrics

        cycles = [
            _cycle(
                "approve",
                "approve",
                [{"key": "B-1"}, {"key": "B-2"}],
                [{"key": "B-1"}, {"key": "B-2"}],
            )
        ]
        m = calculate_metrics(cycles)
        assert m is not None
        assert m["blocker_precision"] == pytest.approx(1.0)
        assert m["blocker_recall"] == pytest.approx(1.0)

    def test_extra_predicted_blockers_lowers_precision(self):
        from scripts.calculate_review_agreement import calculate_metrics

        # Predicted 3, human flagged 2 (one FP)
        cycles = [
            _cycle(
                "request_changes",
                "request_changes",
                [{"key": "B-1"}, {"key": "B-2"}, {"key": "B-3"}],
                [{"key": "B-1"}, {"key": "B-2"}],
            )
        ]
        m = calculate_metrics(cycles)
        assert m is not None
        # TP=2, FP=1 → precision = 2/3
        assert m["blocker_precision"] == pytest.approx(2 / 3)
        # TP=2, FN=0 → recall = 1.0
        assert m["blocker_recall"] == pytest.approx(1.0)

    def test_missing_predicted_blockers_lowers_recall(self):
        from scripts.calculate_review_agreement import calculate_metrics

        # Predicted 1, human flagged 2 (one FN)
        cycles = [
            _cycle(
                "request_changes",
                "request_changes",
                [{"key": "B-1"}],
                [{"key": "B-1"}, {"key": "B-2"}],
            )
        ]
        m = calculate_metrics(cycles)
        assert m is not None
        # TP=1, FP=0 → precision = 1.0
        assert m["blocker_precision"] == pytest.approx(1.0)
        # TP=1, FN=1 → recall = 0.5
        assert m["blocker_recall"] == pytest.approx(0.5)

    def test_both_empty_blocker_sets(self):
        from scripts.calculate_review_agreement import calculate_metrics

        cycles = [_cycle("approve", "approve", [], [])]
        m = calculate_metrics(cycles)
        assert m is not None
        # Both empty → precision=1, recall=1 (correct agreement)
        assert m["blocker_precision"] == pytest.approx(1.0)
        assert m["blocker_recall"] == pytest.approx(1.0)

    def test_none_cycles_returns_none(self):
        from scripts.calculate_review_agreement import calculate_metrics

        assert calculate_metrics([]) is None

    def test_approval_accuracy(self):
        from scripts.calculate_review_agreement import calculate_metrics

        cycles = [
            _cycle("approve", "approve", [], []),
            _cycle("request_changes", "approve", [], []),  # mismatch
        ]
        m = calculate_metrics(cycles)
        assert m is not None
        # 1 out of 2 correct
        assert m["approval_accuracy"] == pytest.approx(0.5)
        assert m["count"] == 2


# ── build_calibration_note ────────────────────────────────────────────────────

class TestBuildCalibrationNote:
    """Unit tests for build_calibration_note() in review_cycles.py."""

    def _session_with_cycles(self, cycles: list) -> AsyncMock:
        session = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = cycles
        session.execute = AsyncMock(return_value=result)
        return session

    @pytest.mark.asyncio
    async def test_returns_none_for_zero_cycles(self):
        from app.review_cycles import build_calibration_note

        session = self._session_with_cycles([])
        note = await build_calibration_note(session, "mini-abc")
        assert note is None

    @pytest.mark.asyncio
    async def test_returns_none_for_one_cycle(self):
        from app.review_cycles import build_calibration_note

        cycles = [_cycle("approve", "approve", [], [])]
        session = self._session_with_cycles(cycles)
        note = await build_calibration_note(session, "mini-abc")
        assert note is None

    @pytest.mark.asyncio
    async def test_returns_note_for_two_or_more_cycles(self):
        from app.review_cycles import build_calibration_note

        cycles = [
            _cycle("approve", "approve", [], []),
            _cycle("request_changes", "request_changes", [{"key": "B-1"}], [{"key": "B-1"}]),
        ]
        session = self._session_with_cycles(cycles)
        note = await build_calibration_note(session, "mini-abc")
        assert note is not None
        assert "Recent Calibration" in note
        assert "blocker precision" in note

    @pytest.mark.asyncio
    async def test_note_includes_precision_and_recall(self):
        from app.review_cycles import build_calibration_note

        # 2 cycles: one perfect match, one FP blocker
        cycles = [
            _cycle(
                "request_changes",
                "request_changes",
                [{"key": "B-1"}, {"key": "B-2"}],
                [{"key": "B-1"}, {"key": "B-2"}],
            ),
            _cycle(
                "request_changes",
                "request_changes",
                [{"key": "B-1"}, {"key": "B-2"}, {"key": "B-3"}],  # B-3 is FP
                [{"key": "B-1"}, {"key": "B-2"}],
            ),
        ]
        session = self._session_with_cycles(cycles)
        note = await build_calibration_note(session, "mini-abc")
        assert note is not None
        # Avg precision = (1.0 + 2/3) / 2 = 0.83; avg recall = (1.0 + 1.0) / 2 = 1.0
        assert "precision" in note
        assert "recall" in note

    @pytest.mark.asyncio
    async def test_low_precision_hint_included(self):
        """Low precision (<0.60) should produce a 'tighten your blocker criteria' hint."""
        from app.review_cycles import build_calibration_note

        # Predicted 5 blockers, human has 1 → precision=0.2
        cycles = [
            _cycle(
                "request_changes",
                "approve",
                [{"key": f"B-{i}"} for i in range(5)],
                [{"key": "B-0"}],
            ),
            _cycle(
                "request_changes",
                "approve",
                [{"key": f"B-{i}"} for i in range(5)],
                [{"key": "B-0"}],
            ),
        ]
        session = self._session_with_cycles(cycles)
        note = await build_calibration_note(session, "mini-abc")
        assert note is not None
        assert "tighten" in note.lower()

    @pytest.mark.asyncio
    async def test_low_recall_hint_included(self):
        """Low recall (<0.60) should produce a 'missing blockers' hint."""
        from app.review_cycles import build_calibration_note

        # Predicted 0 blockers, human has 3 → recall=0.0
        cycles = [
            _cycle(
                "approve",
                "request_changes",
                [],
                [{"key": "B-1"}, {"key": "B-2"}, {"key": "B-3"}],
            ),
            _cycle(
                "approve",
                "request_changes",
                [],
                [{"key": "B-1"}, {"key": "B-2"}, {"key": "B-3"}],
            ),
        ]
        session = self._session_with_cycles(cycles)
        note = await build_calibration_note(session, "mini-abc")
        assert note is not None
        assert "miss" in note.lower()

    @pytest.mark.asyncio
    async def test_custom_limit_produces_note_when_enough_data(self):
        """With enough cycles (≥2), a custom limit still produces a calibration note."""
        from app.review_cycles import build_calibration_note

        cycles = [
            _cycle("approve", "approve", [], []),
            _cycle("approve", "approve", [], []),
            _cycle("approve", "approve", [], []),
        ]
        session = self._session_with_cycles(cycles)
        note = await build_calibration_note(session, "mini-abc", limit=3)
        assert note is not None
        assert "Recent Calibration" in note


# ── _build_predictor_system_prompt ────────────────────────────────────────────

class TestBuildPredictorSystemPromptCalibration:
    """Ensure the calibration note is injected into the system prompt."""

    def _body(self) -> SimpleNamespace:
        return SimpleNamespace(
            artifact_type="pull_request",
            author_model="trusted_peer",
            delivery_context="normal",
            relationship_context=None,
            repo_name="owner/repo",
            title="Add feature X",
            description="Details.",
            artifact_summary="Small refactor.",
            diff_summary="Changed 3 files.",
            changed_files=["foo.py"],
        )

    def test_no_calibration_note_when_none(self):
        from app.core.review_predictor_agent import _build_predictor_system_prompt

        mini = _mini()
        body = self._body()
        prompt = _build_predictor_system_prompt(
            mini, body, artifact_label="Pull Request", calibration_note=None
        )
        assert "Recent Calibration" not in prompt

    def test_calibration_note_injected_when_provided(self):
        from app.core.review_predictor_agent import _build_predictor_system_prompt

        mini = _mini()
        body = self._body()
        note = (
            "## Recent Calibration (last 5 reviews)\n"
            "Avg blocker precision: 0.71, recall: 0.65, approval accuracy: 0.80.\n"
            "You tend to flag too many style issues that the reviewer doesn't block on. "
            "Tighten blocker criteria."
        )
        prompt = _build_predictor_system_prompt(
            mini, body, artifact_label="Pull Request", calibration_note=note
        )
        assert "Recent Calibration" in prompt
        assert "precision: 0.71" in prompt
        assert "Tighten blocker criteria" in prompt

    def test_calibration_note_appears_after_directives(self):
        from app.core.review_predictor_agent import _build_predictor_system_prompt

        mini = _mini()
        body = self._body()
        note = "## Recent Calibration\nAvg blocker precision: 0.80, recall: 0.90."
        prompt = _build_predictor_system_prompt(
            mini, body, artifact_label="Pull Request", calibration_note=note
        )
        directive_pos = prompt.find("REVIEW PREDICTOR DIRECTIVES")
        calibration_pos = prompt.find("Recent Calibration")
        assert directive_pos != -1
        assert calibration_pos != -1
        assert calibration_pos > directive_pos, "Calibration note must come after review directives"

    def test_prompt_includes_base_system_prompt(self):
        from app.core.review_predictor_agent import _build_predictor_system_prompt

        mini = _mini(system_prompt="# MY IDENTITY\nI am the reviewer.")
        body = self._body()
        prompt = _build_predictor_system_prompt(
            mini, body, artifact_label="Pull Request"
        )
        assert "MY IDENTITY" in prompt


# ── GET /by-username/{username}/feedback-memory route ─────────────────────────

class TestFeedbackMemoryByUsernameRoute:
    """Test the new username-based feedback-memory endpoint handler logic."""

    @pytest.mark.asyncio
    async def test_raises_404_when_mini_not_found(self):
        """Handler raises HTTPException(404) when username resolves to nothing."""
        import fastapi

        from app.routes.minis import get_feedback_memory_by_username

        session = AsyncMock()
        # user=None → only the public query runs; it returns nothing
        no_public = MagicMock()
        no_public.scalars.return_value.first.return_value = None
        session.execute = AsyncMock(return_value=no_public)

        with pytest.raises(fastapi.HTTPException) as exc_info:
            await get_feedback_memory_by_username(
                "nobody", limit=20, session=session, user=None
            )

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_memories(self):
        """Handler returns [] when mini exists but has no feedback rows."""
        from app.routes.minis import get_feedback_memory_by_username

        mini = _mini()

        session = AsyncMock()
        no_owned = MagicMock()
        no_owned.scalar_one_or_none.return_value = None
        public_result = MagicMock()
        public_result.scalars.return_value.first.return_value = mini
        session.execute = AsyncMock(side_effect=[no_owned, public_result])

        with patch(
            "app.routes.minis.list_prediction_feedback_memories",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_feedback_memory_by_username(
                "reviewer", limit=20, session=session, user=None
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_uses_owned_mini_when_authenticated(self):
        """When user is authenticated with a mini, it uses that mini's id."""
        from app.routes.minis import get_feedback_memory_by_username

        user = SimpleNamespace(id="owner-1", github_username="reviewer")
        mini = _mini(owner_id="owner-1")

        session = AsyncMock()
        owned_result = MagicMock()
        owned_result.scalar_one_or_none.return_value = mini
        session.execute = AsyncMock(return_value=owned_result)

        with patch(
            "app.routes.minis.list_prediction_feedback_memories",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_feedback_memory_by_username(
                "reviewer", limit=20, session=session, user=user
            )

        assert result == []
        # Should have called execute once (owned mini path only)
        assert session.execute.call_count == 1
