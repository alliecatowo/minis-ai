import datetime
import logging

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin import is_trusted_admin
from app.models.rate_limit import RateLimitEvent
from app.models.user import User
from app.models.user_settings import UserSettings

logger = logging.getLogger(__name__)

RATE_LIMITS: dict[str, int] = {
    "mini_create": 1,
    "chat_message": 25,
    "team_chat": 15,
    "file_upload": 5,
}


def _is_admin_user(user: User | None) -> bool:
    """Backward-compatible rate-limit wrapper around trusted admin auth."""
    return is_trusted_admin(user)


async def check_rate_limit(user_id: str, event_type: str, session: AsyncSession) -> None:
    limit = RATE_LIMITS.get(event_type)
    if limit is None:
        return

    # Check exemptions: BYOK only. Admin authority must come from trusted auth.
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    user_settings = result.scalar_one_or_none()
    if user_settings and user_settings.llm_api_key:
        logger.info(
            "rate_limit bypass: user %s has BYOK, skipping %s limit",
            user_id,
            event_type,
        )
        return

    # Check exemptions: admin username list from config
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if _is_admin_user(user):
        logger.info(
            "rate_limit bypass: trusted admin username match for user %s (github_username=%r), skipping %s limit",
            user_id,
            user.github_username if user else None,
            event_type,
        )
        return
    if user:
        logger.info(
            "rate_limit no bypass: user %s (github_username=%r) is not a trusted admin",
            user_id,
            user.github_username,
        )

    # Count events in the last 24 hours
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    result = await session.execute(
        select(func.count())
        .select_from(RateLimitEvent)
        .where(
            RateLimitEvent.user_id == user_id,
            RateLimitEvent.event_type == event_type,
            RateLimitEvent.created_at >= cutoff,
        )
    )
    count = result.scalar_one()

    if count >= limit:
        # Calculate reset time from the oldest event in the window
        oldest_result = await session.execute(
            select(RateLimitEvent.created_at)
            .where(
                RateLimitEvent.user_id == user_id,
                RateLimitEvent.event_type == event_type,
                RateLimitEvent.created_at >= cutoff,
            )
            .order_by(RateLimitEvent.created_at.asc())
            .limit(1)
        )
        oldest_time = oldest_result.scalar_one()
        reset_time = oldest_time + datetime.timedelta(hours=24)
        hours_remaining = max(
            1,
            int((reset_time - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600),
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: {limit} {event_type} per day. "
                f"Resets in {hours_remaining} hours. "
                "Add your own API key in Settings to remove limits."
            ),
        )

    # Record the event
    session.add(RateLimitEvent(user_id=user_id, event_type=event_type))
    await session.flush()
    await session.commit()
