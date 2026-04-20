"""Tests for app/core/llm.py.

Covers:
- _check_budget: None user bypass, user budget exceeded, global budget exceeded,
  DB exceptions swallowed, both budgets under limit.
- _record_usage: happy path (user_id present + absent), alert triggers,
  expensive request alert, DB exception swallowed.
- llm_completion: success path, budget exceeded propagates, model defaults.
- llm_completion_json: success path, budget exceeded propagates.
- llm_stream: success path, budget exceeded propagates, message parsing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Local fixture: patches app.core.llm.Agent (the bound name in llm.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm_agent():
    """Patch app.core.llm.Agent so no real LLM provider is instantiated."""
    mock_result = MagicMock()
    mock_result.output = "Mocked LLM response"
    mock_result.usage.return_value = MagicMock(input_tokens=10, output_tokens=20)

    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=mock_result)

    mock_agent_class = MagicMock(return_value=mock_agent_instance)

    with patch("app.core.llm.Agent", mock_agent_class):
        yield mock_agent_class


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user_budget(spent: float, budget: float) -> MagicMock:
    ub = MagicMock()
    ub.total_spent_usd = spent
    ub.monthly_budget_usd = budget
    return ub


def _make_global_budget(spent: float, budget: float) -> MagicMock:
    gb = MagicMock()
    gb.total_spent_usd = spent
    gb.monthly_budget_usd = budget
    gb.key = "global"
    return gb


# ---------------------------------------------------------------------------
# _check_budget
# ---------------------------------------------------------------------------


class TestCheckBudget:
    @pytest.mark.asyncio
    async def test_none_user_id_returns_immediately(self):
        from app.core.llm import _check_budget

        # Should not touch DB at all; no mock needed.
        await _check_budget(None)

    @pytest.mark.asyncio
    async def test_under_budget_does_not_raise(self):
        from app.core.llm import _check_budget

        user_budget = _make_user_budget(1.0, 5.0)
        global_budget = _make_global_budget(10.0, 100.0)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        # First execute → UserBudget row; second execute → GlobalBudget row
        mock_session.execute = AsyncMock(
            side_effect=[
                _result(user_budget),
                _result(global_budget),
            ]
        )

        with patch("app.db.async_session", return_value=mock_session):
            await _check_budget("user-123")  # must not raise

    @pytest.mark.asyncio
    async def test_user_budget_exceeded_raises(self):
        from app.core.llm import BudgetExceededError, _check_budget

        user_budget = _make_user_budget(5.0, 5.0)  # at limit → >= triggers

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=_result(user_budget))

        with patch("app.db.async_session", return_value=mock_session):
            with pytest.raises(BudgetExceededError, match="Monthly budget"):
                await _check_budget("user-123")

    @pytest.mark.asyncio
    async def test_global_budget_exceeded_raises(self):
        from app.core.llm import BudgetExceededError, _check_budget

        user_budget = _make_user_budget(1.0, 5.0)  # fine
        global_budget = _make_global_budget(100.0, 100.0)  # at limit

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(
            side_effect=[
                _result(user_budget),
                _result(global_budget),
            ]
        )

        with patch("app.db.async_session", return_value=mock_session):
            with pytest.raises(BudgetExceededError, match="Platform-wide"):
                await _check_budget("user-123")

    @pytest.mark.asyncio
    async def test_no_user_budget_row_does_not_raise(self):
        """When there's no UserBudget row, skip user check and continue."""
        from app.core.llm import _check_budget

        global_budget = _make_global_budget(10.0, 100.0)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(
            side_effect=[
                _result(None),  # no UserBudget row
                _result(global_budget),
            ]
        )

        with patch("app.db.async_session", return_value=mock_session):
            await _check_budget("user-123")

    @pytest.mark.asyncio
    async def test_no_global_budget_row_does_not_raise(self):
        """When there's no GlobalBudget row, skip global check."""
        from app.core.llm import _check_budget

        user_budget = _make_user_budget(1.0, 5.0)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(
            side_effect=[
                _result(user_budget),
                _result(None),  # no GlobalBudget row
            ]
        )

        with patch("app.db.async_session", return_value=mock_session):
            await _check_budget("user-123")

    @pytest.mark.asyncio
    async def test_db_exception_is_swallowed(self):
        """Non-BudgetExceededError DB failures are swallowed."""
        from app.core.llm import _check_budget

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.async_session", return_value=mock_session):
            await _check_budget("user-123")  # must not raise

    @pytest.mark.asyncio
    async def test_budget_exceeded_is_reraised_not_swallowed(self):
        """BudgetExceededError must propagate even though it comes from inside try."""
        from app.core.llm import BudgetExceededError, _check_budget

        user_budget = _make_user_budget(10.0, 5.0)  # over limit

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=_result(user_budget))

        with patch("app.db.async_session", return_value=mock_session):
            with pytest.raises(BudgetExceededError):
                await _check_budget("user-123")


# ---------------------------------------------------------------------------
# _record_usage
# ---------------------------------------------------------------------------


class TestRecordUsage:
    @pytest.mark.asyncio
    async def test_records_event_without_user(self):
        """Usage event is written even when user_id is None."""
        from app.core.llm import _record_usage

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        # GlobalBudget row
        global_budget = _make_global_budget(1.0, 100.0)
        mock_session.execute = AsyncMock(return_value=_result(global_budget))
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch("app.core.alerts.alert_expensive_request"),
        ):
            await _record_usage(None, "test-model", 100, 50, 0.01)

        mock_session.add.assert_called()
        mock_session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_records_event_with_user(self):
        """With user_id, UserBudget is fetched and updated."""
        from app.core.llm import _record_usage

        user_budget = _make_user_budget(1.0, 10.0)
        user_budget.total_spent_usd = 1.0  # allow += in production code
        global_budget = _make_global_budget(5.0, 100.0)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(
            side_effect=[
                _result(user_budget),
                _result(global_budget),
            ]
        )
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch("app.db.async_session", return_value=mock_session):
            await _record_usage("user-1", "test-model", 100, 50, 0.01)

        mock_session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_creates_user_budget_row_when_missing(self):
        """When no UserBudget row exists, a new one is inserted."""
        from app.core.llm import _record_usage

        global_budget = _make_global_budget(5.0, 100.0)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        # First call returns None (no user budget row), second for global
        mock_session.execute = AsyncMock(
            side_effect=[
                _result(None),  # no UserBudget
                _result(global_budget),
            ]
        )
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch("app.db.async_session", return_value=mock_session):
            await _record_usage("user-new", "test-model", 100, 50, 0.01)

        # add should be called at least twice (usage event + new user budget)
        assert mock_session.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_creates_global_budget_row_when_missing(self):
        """When no GlobalBudget row exists, a new one is inserted."""
        from app.core.llm import _record_usage

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        # No global budget row
        mock_session.execute = AsyncMock(return_value=_result(None))
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch("app.db.async_session", return_value=mock_session):
            await _record_usage(None, "test-model", 100, 50, 0.01)

        # add should have been called for usage event + new global budget
        assert mock_session.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_alert_budget_threshold_triggered_at_80_pct(self):
        """alert_budget_threshold fires when user spend >= 80% of budget."""
        from app.core.llm import _record_usage

        # 8.0 / 10.0 = 80% exactly
        user_budget = _make_user_budget(7.99, 10.0)
        global_budget = _make_global_budget(5.0, 100.0)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(
            side_effect=[
                _result(user_budget),
                _result(global_budget),
            ]
        )
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch("app.core.alerts.alert_budget_threshold") as mock_alert,
        ):
            # cost_usd=0.01 pushes spent to 7.99+0.01=8.0 → 80%
            await _record_usage("user-1", "test-model", 100, 50, 0.01)

        mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_alert_global_threshold_triggered_at_80_pct(self):
        """alert_global_threshold fires when global spend >= 80%."""
        from app.core.llm import _record_usage

        user_budget = _make_user_budget(1.0, 10.0)
        # 79.99+0.01=80.0 → 80%
        global_budget = _make_global_budget(79.99, 100.0)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(
            side_effect=[
                _result(user_budget),
                _result(global_budget),
            ]
        )
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch("app.core.alerts.alert_global_threshold") as mock_alert,
        ):
            await _record_usage("user-1", "test-model", 100, 50, 0.01)

        mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_expensive_request_alert_triggered_over_50_cents(self):
        """alert_expensive_request fires when cost > $0.50."""
        from app.core.llm import _record_usage

        global_budget = _make_global_budget(5.0, 100.0)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=_result(global_budget))
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch("app.core.alerts.alert_expensive_request") as mock_alert,
        ):
            await _record_usage(None, "test-model", 100_000, 50_000, 0.51)

        mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_expensive_request_alert_not_triggered_under_50_cents(self):
        """alert_expensive_request does NOT fire when cost <= $0.50."""
        from app.core.llm import _record_usage

        global_budget = _make_global_budget(5.0, 100.0)

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=_result(global_budget))
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch("app.core.alerts.alert_expensive_request") as mock_alert,
        ):
            await _record_usage(None, "test-model", 100, 50, 0.50)

        mock_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_db_exception_is_swallowed(self):
        """Exceptions in _record_usage are caught; caller is not interrupted."""
        from app.core.llm import _record_usage

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(side_effect=RuntimeError("DB exploded"))
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.db.async_session", return_value=mock_session):
            await _record_usage("user-1", "test-model", 100, 50, 0.01)  # must not raise

    @pytest.mark.asyncio
    async def test_zero_budget_skips_threshold_alert(self):
        """No threshold alert when monthly_budget_usd is 0 (division guard)."""
        from app.core.llm import _record_usage

        user_budget = _make_user_budget(1.0, 0.0)  # zero budget
        global_budget = _make_global_budget(1.0, 0.0)  # zero global budget

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(
            side_effect=[
                _result(user_budget),
                _result(global_budget),
            ]
        )
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch("app.core.alerts.alert_budget_threshold") as mock_user_alert,
            patch("app.core.alerts.alert_global_threshold") as mock_global_alert,
        ):
            await _record_usage("user-1", "test-model", 100, 50, 0.01)

        mock_user_alert.assert_not_called()
        mock_global_alert.assert_not_called()


# ---------------------------------------------------------------------------
# llm_completion
# ---------------------------------------------------------------------------


class TestLlmCompletion:
    @pytest.mark.asyncio
    async def test_returns_output_on_success(self, mock_llm_agent):
        from app.core.llm import llm_completion

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
        ):
            result = await llm_completion("Hello!")

        assert result == "Mocked LLM response"

    @pytest.mark.asyncio
    async def test_passes_system_prompt(self, mock_llm_agent):
        from app.core.llm import llm_completion

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
        ):
            await llm_completion("Hello!", system="You are a helper.")

        # Agent was constructed with instructions keyword
        mock_llm_agent.assert_called_once()
        _, kwargs = mock_llm_agent.call_args
        assert kwargs.get("instructions") == "You are a helper."

    @pytest.mark.asyncio
    async def test_empty_system_prompt_passes_none(self, mock_llm_agent):
        from app.core.llm import llm_completion

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
        ):
            await llm_completion("Hello!")

        _, kwargs = mock_llm_agent.call_args
        assert kwargs.get("instructions") is None

    @pytest.mark.asyncio
    async def test_budget_exceeded_propagates(self):
        from app.core.llm import BudgetExceededError, llm_completion

        with patch(
            "app.core.llm._check_budget",
            AsyncMock(side_effect=BudgetExceededError("Over limit")),
        ):
            with pytest.raises(BudgetExceededError, match="Over limit"):
                await llm_completion("Hello!", user_id="user-1")

    @pytest.mark.asyncio
    async def test_uses_fast_tier_model_by_default(self, mock_llm_agent):
        from app.core.llm import llm_completion
        from app.core.models import ModelTier, get_model

        expected_model = get_model(ModelTier.FAST)

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
        ):
            await llm_completion("Hello!")

        args, _ = mock_llm_agent.call_args
        assert args[0] == expected_model

    @pytest.mark.asyncio
    async def test_custom_model_overrides_default(self, mock_llm_agent):
        from app.core.llm import llm_completion

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
        ):
            await llm_completion("Hello!", model="openai:gpt-4.1-mini")

        args, _ = mock_llm_agent.call_args
        assert args[0] == "openai:gpt-4.1-mini"

    @pytest.mark.asyncio
    async def test_record_usage_called_with_correct_endpoint(self, mock_llm_agent):
        from app.core.llm import llm_completion

        mock_record = AsyncMock()
        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", mock_record),
        ):
            await llm_completion("Hello!", user_id="user-1")

        mock_record.assert_awaited_once()
        kwargs = mock_record.call_args
        assert kwargs[1].get("endpoint") == "llm_completion" or (
            len(kwargs[0]) >= 6 and kwargs[0][5] == "llm_completion"
        )


# ---------------------------------------------------------------------------
# llm_completion_json
# ---------------------------------------------------------------------------


class TestLlmCompletionJson:
    @pytest.mark.asyncio
    async def test_returns_output_on_success(self, mock_llm_agent):
        from app.core.llm import llm_completion_json

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
        ):
            result = await llm_completion_json("Give me JSON.")

        assert result == "Mocked LLM response"

    @pytest.mark.asyncio
    async def test_budget_exceeded_propagates(self):
        from app.core.llm import BudgetExceededError, llm_completion_json

        with patch(
            "app.core.llm._check_budget",
            AsyncMock(side_effect=BudgetExceededError("Over limit")),
        ):
            with pytest.raises(BudgetExceededError):
                await llm_completion_json("Hello!", user_id="user-1")

    @pytest.mark.asyncio
    async def test_uses_fast_tier_model_by_default(self, mock_llm_agent):
        from app.core.llm import llm_completion_json
        from app.core.models import ModelTier, get_model

        expected = get_model(ModelTier.FAST)

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
        ):
            await llm_completion_json("Hello!")

        args, _ = mock_llm_agent.call_args
        assert args[0] == expected

    @pytest.mark.asyncio
    async def test_record_usage_called_with_json_endpoint(self, mock_llm_agent):
        from app.core.llm import llm_completion_json

        mock_record = AsyncMock()
        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", mock_record),
        ):
            await llm_completion_json("Hello!")

        mock_record.assert_awaited_once()


# ---------------------------------------------------------------------------
# llm_stream
# ---------------------------------------------------------------------------


class TestLlmStream:
    def _make_streaming_agent(self, chunks: list[str]) -> MagicMock:
        """Build a mock PydanticAI agent that streams the given text chunks."""
        mock_response = MagicMock()
        mock_response.usage.return_value = MagicMock(input_tokens=10, output_tokens=20)

        async def _stream_text(delta=True):
            for chunk in chunks:
                yield chunk

        mock_response.stream_text = _stream_text
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_agent = MagicMock()
        mock_agent.run_stream = MagicMock(return_value=mock_response)

        mock_agent_class = MagicMock(return_value=mock_agent)
        return mock_agent_class

    @pytest.mark.asyncio
    async def test_yields_chunks(self):
        from app.core.llm import llm_stream

        mock_agent_class = self._make_streaming_agent(["Hello", " world"])

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
            patch("app.core.llm.Agent", mock_agent_class),
        ):
            chunks = []
            async for chunk in llm_stream([{"role": "user", "content": "Hi"}]):
                chunks.append(chunk)

        assert chunks == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_budget_exceeded_propagates(self):
        from app.core.llm import BudgetExceededError, llm_stream

        with patch(
            "app.core.llm._check_budget",
            AsyncMock(side_effect=BudgetExceededError("Over limit")),
        ):
            with pytest.raises(BudgetExceededError):
                async for _ in llm_stream([{"role": "user", "content": "Hi"}], user_id="user-1"):
                    pass

    @pytest.mark.asyncio
    async def test_extracts_system_and_user_from_messages(self):
        """System prompt and user message are parsed correctly from messages list."""
        from app.core.llm import llm_stream

        mock_agent_class = self._make_streaming_agent(["reply"])

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
            patch("app.core.llm.Agent", mock_agent_class),
        ):
            chunks = []
            async for chunk in llm_stream(
                [
                    {"role": "system", "content": "Be helpful."},
                    {"role": "user", "content": "What is 2+2?"},
                ]
            ):
                chunks.append(chunk)

        # Agent constructed with system as instructions
        _, kwargs = mock_agent_class.call_args
        assert kwargs.get("instructions") == "Be helpful."
        # run_stream called with user message
        mock_agent_class.return_value.run_stream.assert_called_once_with("What is 2+2?")

    @pytest.mark.asyncio
    async def test_falls_back_to_last_message_when_no_user_role(self):
        """When no 'user' role message is present, last message content is used."""
        from app.core.llm import llm_stream

        mock_agent_class = self._make_streaming_agent(["ok"])

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
            patch("app.core.llm.Agent", mock_agent_class),
        ):
            async for _ in llm_stream([{"role": "assistant", "content": "fallback-msg"}]):
                pass

        mock_agent_class.return_value.run_stream.assert_called_once_with("fallback-msg")

    @pytest.mark.asyncio
    async def test_empty_messages_does_not_crash(self):
        """Empty messages list falls back to empty user message."""
        from app.core.llm import llm_stream

        mock_agent_class = self._make_streaming_agent([])

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
            patch("app.core.llm.Agent", mock_agent_class),
        ):
            chunks = []
            async for chunk in llm_stream([]):
                chunks.append(chunk)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_uses_standard_tier_model_by_default(self):
        from app.core.llm import llm_stream
        from app.core.models import ModelTier, get_model

        expected = get_model(ModelTier.STANDARD)
        mock_agent_class = self._make_streaming_agent(["x"])

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
            patch("app.core.llm.Agent", mock_agent_class),
        ):
            async for _ in llm_stream([{"role": "user", "content": "hi"}]):
                pass

        args, _ = mock_agent_class.call_args
        assert args[0] == expected

    @pytest.mark.asyncio
    async def test_custom_model_overrides_default(self):
        from app.core.llm import llm_stream

        mock_agent_class = self._make_streaming_agent(["x"])

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", AsyncMock()),
            patch("app.core.llm.Agent", mock_agent_class),
        ):
            async for _ in llm_stream(
                [{"role": "user", "content": "hi"}], model="openai:gpt-4.1-mini"
            ):
                pass

        args, _ = mock_agent_class.call_args
        assert args[0] == "openai:gpt-4.1-mini"

    @pytest.mark.asyncio
    async def test_record_usage_called_after_stream(self):
        from app.core.llm import llm_stream

        mock_agent_class = self._make_streaming_agent(["chunk1", "chunk2"])
        mock_record = AsyncMock()

        with (
            patch("app.core.llm._check_budget", AsyncMock()),
            patch("app.core.llm._record_usage", mock_record),
            patch("app.core.llm.Agent", mock_agent_class),
        ):
            async for _ in llm_stream([{"role": "user", "content": "hi"}]):
                pass

        mock_record.assert_awaited_once()


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _result(value) -> MagicMock:
    """Return a mock that mimics `await session.execute(...)` → `.scalar_one_or_none()`."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r
