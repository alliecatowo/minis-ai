"""LLM utilities built on PydanticAI.

Provides simple completion helpers (single-shot, JSON, streaming) with
budget metering. All model resolution goes through app.core.models.
"""

import logging
from collections.abc import AsyncGenerator

from pydantic_ai import Agent

from app.core.models import ModelTier, get_model

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when a user or the platform has exceeded their LLM budget."""

    def __init__(self, message: str = "LLM budget exceeded"):
        self.message = message
        super().__init__(self.message)


def setup_langfuse() -> None:
    """No-op — Langfuse integration has been removed.

    Kept as a stub so callers (main.py lifespan) don't break.
    """
    logger.debug("Langfuse integration removed (pydantic-ai migration)")


async def _check_budget(user_id: str | None) -> None:
    """Check user and global budgets before making an LLM call.

    Raises BudgetExceededError if the budget is exhausted.
    Does nothing if user_id is None (unauthenticated/system calls).
    """
    if user_id is None:
        return

    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models.usage import GlobalBudget, UserBudget

        async with async_session() as session:
            # Check user budget
            result = await session.execute(select(UserBudget).where(UserBudget.user_id == user_id))
            user_budget = result.scalar_one_or_none()
            if user_budget and user_budget.total_spent_usd >= user_budget.monthly_budget_usd:
                raise BudgetExceededError(
                    f"Monthly budget of ${user_budget.monthly_budget_usd:.2f} exceeded"
                )

            # Check global budget
            result = await session.execute(select(GlobalBudget).where(GlobalBudget.key == "global"))
            global_budget = result.scalar_one_or_none()
            if global_budget and global_budget.total_spent_usd >= global_budget.monthly_budget_usd:
                raise BudgetExceededError("Platform-wide LLM budget exceeded")
    except BudgetExceededError:
        raise
    except Exception:
        logger.debug("Budget check failed (non-blocking)", exc_info=True)


async def _record_usage(
    user_id: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    endpoint: str | None = None,
    error: str | None = None,
) -> None:
    """Record an LLM usage event to the database.

    Never raises -- failures are logged and swallowed so metering
    does not break the caller.
    """
    try:
        from app.core.alerts import (
            alert_budget_threshold,
            alert_expensive_request,
            alert_global_threshold,
        )
        from app.db import async_session
        from app.models.usage import GlobalBudget, LLMUsageEvent, UserBudget

        async with async_session() as session:
            # 1. Write the usage event
            event = LLMUsageEvent(
                user_id=user_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                cost_usd=cost_usd,
                endpoint=endpoint,
                error=error,
            )
            session.add(event)

            # 2. Update user budget running total
            if user_id:
                from sqlalchemy import select

                result = await session.execute(
                    select(UserBudget).where(UserBudget.user_id == user_id)
                )
                user_budget = result.scalar_one_or_none()
                if user_budget is None:
                    user_budget = UserBudget(user_id=user_id)
                    session.add(user_budget)
                    await session.flush()
                user_budget.total_spent_usd += cost_usd

                # Alert at 80% threshold
                if user_budget.monthly_budget_usd > 0:
                    pct = user_budget.total_spent_usd / user_budget.monthly_budget_usd
                    if pct >= 0.8:
                        alert_budget_threshold(
                            user_id,
                            user_budget.total_spent_usd,
                            user_budget.monthly_budget_usd,
                            pct,
                        )

            # 3. Update global budget running total
            from sqlalchemy import select

            result = await session.execute(select(GlobalBudget).where(GlobalBudget.key == "global"))
            global_budget = result.scalar_one_or_none()
            if global_budget is None:
                global_budget = GlobalBudget()
                session.add(global_budget)
                await session.flush()
            global_budget.total_spent_usd += cost_usd

            if global_budget.monthly_budget_usd > 0:
                pct = global_budget.total_spent_usd / global_budget.monthly_budget_usd
                if pct >= 0.8:
                    alert_global_threshold(
                        global_budget.total_spent_usd,
                        global_budget.monthly_budget_usd,
                        pct,
                    )

            await session.commit()

        # 4. Alert on expensive single requests
        if cost_usd > 0.50:
            alert_expensive_request(user_id, model, cost_usd, input_tokens + output_tokens)

    except Exception:
        logger.error("Failed to record LLM usage event", exc_info=True)


async def llm_completion(
    prompt: str,
    system: str = "",
    model: str | None = None,
    api_key: str | None = None,
    user_id: str | None = None,
) -> str:
    """Single-shot LLM completion. Returns the assistant message content."""
    resolved_model = model or get_model(ModelTier.FAST)
    await _check_budget(user_id)

    agent = Agent(resolved_model, instructions=system if system else None)
    result = await agent.run(prompt)

    # Record usage
    usage = result.usage()
    from app.core.pricing import calculate_cost

    cost = calculate_cost(resolved_model, usage.input_tokens or 0, usage.output_tokens or 0)
    await _record_usage(
        user_id,
        resolved_model,
        usage.input_tokens or 0,
        usage.output_tokens or 0,
        cost,
        endpoint="llm_completion",
    )

    return result.output


async def llm_completion_json(
    prompt: str,
    system: str = "",
    model: str | None = None,
    api_key: str | None = None,
    user_id: str | None = None,
) -> str:
    """LLM completion with JSON response format. Returns raw string (caller parses)."""
    resolved_model = model or get_model(ModelTier.FAST)
    await _check_budget(user_id)

    agent = Agent(resolved_model, instructions=system if system else None)
    result = await agent.run(prompt)

    # Record usage
    usage = result.usage()
    from app.core.pricing import calculate_cost

    cost = calculate_cost(resolved_model, usage.input_tokens or 0, usage.output_tokens or 0)
    await _record_usage(
        user_id,
        resolved_model,
        usage.input_tokens or 0,
        usage.output_tokens or 0,
        cost,
        endpoint="llm_completion_json",
    )

    return result.output


async def llm_stream(
    messages: list[dict],
    model: str | None = None,
    api_key: str | None = None,
    user_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """Streaming LLM completion. Yields content deltas as strings.

    Token usage is recorded after the stream completes.
    """
    resolved_model = model or get_model(ModelTier.STANDARD)
    await _check_budget(user_id)

    # Extract system prompt and user message from messages list
    system_prompt = ""
    user_message = ""
    for msg in messages:
        if msg.get("role") == "system":
            system_prompt = msg.get("content", "")
        elif msg.get("role") == "user":
            user_message = msg.get("content", "")

    if not user_message:
        # Fallback: use last message content
        user_message = messages[-1].get("content", "") if messages else ""

    agent = Agent(resolved_model, instructions=system_prompt if system_prompt else None)

    async with agent.run_stream(user_message) as response:
        async for text in response.stream_text(delta=True):
            yield text

    # Record usage after stream completes
    usage = response.usage()
    from app.core.pricing import calculate_cost

    cost = calculate_cost(
        resolved_model,
        usage.input_tokens or 0,
        usage.output_tokens or 0,
    )
    await _record_usage(
        user_id,
        resolved_model,
        usage.input_tokens or 0,
        usage.output_tokens or 0,
        cost,
        endpoint="llm_stream",
    )
