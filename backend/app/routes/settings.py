import datetime
import logging
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.encryption import encrypt_value
from app.core.models import ModelTier, PROVIDER_DEFAULTS
from app.core.rate_limit import RATE_LIMITS
from app.db import get_session
from app.models.rate_limit import RateLimitEvent
from app.models.user import User
from app.models.user_settings import UserSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])

# -----------------------------------------------------------------
# Static model catalogue (per-provider, for the "single model" picker)
# -----------------------------------------------------------------
AVAILABLE_MODELS = {
    "gemini": [
        {"id": "gemini/gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        {"id": "gemini/gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
    ],
    "openai": [
        {"id": "gpt-4o", "name": "GPT-4o"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini"},
    ],
    "anthropic": [
        {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
        {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
    ],
}

# Tier-aware model catalogue: provider → tier → list of {id, name}
TIER_MODELS: dict[str, dict[str, list[dict[str, str]]]] = {
    "gemini": {
        "fast": [
            {"id": "gemini:gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        ],
        "standard": [
            {"id": "gemini:gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
            {"id": "gemini:gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
        ],
        "thinking": [
            {"id": "gemini:gemini-2.5-pro", "name": "Gemini 2.5 Pro"},
            {"id": "gemini:gemini-2.5-flash", "name": "Gemini 2.5 Flash"},
        ],
    },
    "openai": {
        "fast": [
            {"id": "openai:gpt-4.1-mini", "name": "GPT-4.1 Mini"},
            {"id": "openai:gpt-4o-mini", "name": "GPT-4o Mini"},
        ],
        "standard": [
            {"id": "openai:gpt-4.1", "name": "GPT-4.1"},
            {"id": "openai:gpt-4o", "name": "GPT-4o"},
        ],
        "thinking": [
            {"id": "openai:o4-mini", "name": "o4-mini"},
            {"id": "openai:o3", "name": "o3"},
        ],
    },
    "anthropic": {
        "fast": [
            {"id": "anthropic:claude-haiku-4-5", "name": "Claude Haiku 4.5"},
        ],
        "standard": [
            {"id": "anthropic:claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
            {"id": "anthropic:claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
        ],
        "thinking": [
            {"id": "anthropic:claude-sonnet-4-6", "name": "Claude Sonnet 4.6"},
            {"id": "anthropic:claude-opus-4-5", "name": "Claude Opus 4.5"},
        ],
    },
}

# Key format validators for test-key endpoint
_KEY_PATTERNS: dict[str, re.Pattern] = {
    "gemini": re.compile(r"^AIza[A-Za-z0-9_-]{35,}$"),
    "openai": re.compile(r"^sk-[A-Za-z0-9_-]{20,}$"),
    "anthropic": re.compile(r"^sk-ant-[A-Za-z0-9_-]{20,}$"),
}


# -----------------------------------------------------------------
# Pydantic schemas
# -----------------------------------------------------------------


class SettingsResponse(BaseModel):
    llm_provider: str
    preferred_model: str | None
    has_api_key: bool
    is_admin: bool
    model_preferences: dict[str, str] | None = None


class UpdateSettingsRequest(BaseModel):
    llm_api_key: str | None = Field(default=None, max_length=500)
    llm_provider: str | None = Field(default=None, max_length=50)
    preferred_model: str | None = Field(default=None, max_length=255)
    model_preferences: dict[str, str] | None = Field(default=None)


class UsageResponse(BaseModel):
    mini_creates_today: int
    mini_create_limit: int
    chat_messages_today: int
    chat_message_limit: int
    is_exempt: bool


class TestKeyRequest(BaseModel):
    api_key: str = Field(max_length=500)
    provider: str = Field(max_length=50)


class TestKeyResponse(BaseModel):
    valid: bool
    message: str


class TierModelsResponse(BaseModel):
    """Available models grouped by provider and tier."""

    providers: dict[str, dict[str, list[dict[str, str]]]]
    tiers: list[str]
    defaults: dict[str, dict[str, str]]


# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------


def _build_settings_response(user_settings: UserSettings, github_username: str) -> SettingsResponse:
    return SettingsResponse(
        llm_provider=user_settings.llm_provider,
        preferred_model=user_settings.preferred_model,
        has_api_key=bool(user_settings.llm_api_key),
        is_admin=user_settings.is_admin or github_username.lower() in settings.admin_username_list,
        model_preferences=user_settings.model_preferences,
    )


# -----------------------------------------------------------------
# Routes
# -----------------------------------------------------------------


@router.get("")
async def get_settings(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SettingsResponse:
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    user_settings = result.scalar_one_or_none()
    if not user_settings:
        return SettingsResponse(
            llm_provider="gemini",
            preferred_model=None,
            has_api_key=False,
            is_admin=bool(
                user.github_username
                and user.github_username.lower() in settings.admin_username_list
            ),
            model_preferences=None,
        )
    return _build_settings_response(user_settings, user.github_username)


@router.put("")
async def update_settings(
    body: UpdateSettingsRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SettingsResponse:
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    user_settings = result.scalar_one_or_none()
    if not user_settings:
        user_settings = UserSettings(user_id=user.id)
        session.add(user_settings)

    if body.llm_api_key is not None:
        user_settings.llm_api_key = encrypt_value(body.llm_api_key) if body.llm_api_key else None
    if body.llm_provider is not None:
        user_settings.llm_provider = body.llm_provider
    if body.preferred_model is not None:
        user_settings.preferred_model = body.preferred_model or None
    if body.model_preferences is not None:
        user_settings.model_preferences = body.model_preferences

    await session.commit()
    await session.refresh(user_settings)

    return _build_settings_response(user_settings, user.github_username)


@router.get("/usage")
async def get_usage(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UsageResponse:
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    # Check exemption status
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user.id))
    user_settings = result.scalar_one_or_none()
    is_exempt = False
    if user_settings:
        if user_settings.llm_api_key or user_settings.is_admin:
            is_exempt = True
    if user.github_username and user.github_username.lower() in settings.admin_username_list:
        is_exempt = True

    # Count events in last 24h
    mini_creates = 0
    chat_messages = 0
    for event_type, attr in [("mini_create", "mini_creates"), ("chat_message", "chat_messages")]:
        result = await session.execute(
            select(func.count())
            .select_from(RateLimitEvent)
            .where(
                RateLimitEvent.user_id == user.id,
                RateLimitEvent.event_type == event_type,
                RateLimitEvent.created_at >= cutoff,
            )
        )
        count = result.scalar_one()
        if event_type == "mini_create":
            mini_creates = count
        else:
            chat_messages = count

    return UsageResponse(
        mini_creates_today=mini_creates,
        mini_create_limit=RATE_LIMITS["mini_create"],
        chat_messages_today=chat_messages,
        chat_message_limit=RATE_LIMITS["chat_message"],
        is_exempt=is_exempt,
    )


@router.get("/models")
async def get_available_models():
    """Get available LLM models grouped by provider."""
    return AVAILABLE_MODELS


@router.get("/models/tiers")
async def get_tier_models() -> TierModelsResponse:
    """Get available models per provider per tier, plus system defaults."""
    # Build defaults dict: provider → tier → default model id
    defaults: dict[str, dict[str, str]] = {}
    for provider, tier_map in PROVIDER_DEFAULTS.items():
        defaults[provider.value] = {
            tier.value: model_id
            for tier, model_id in tier_map.items()
            if tier != ModelTier.EMBEDDING
        }

    return TierModelsResponse(
        providers=TIER_MODELS,
        tiers=["fast", "standard", "thinking"],
        defaults=defaults,
    )


@router.post("/test-key")
async def test_api_key(
    body: TestKeyRequest,
    user: User = Depends(get_current_user),
) -> TestKeyResponse:
    """Validate an API key by checking its format and making a minimal test call."""
    provider = body.provider.lower()
    api_key = body.api_key.strip()

    # Fast format check
    pattern = _KEY_PATTERNS.get(provider)
    if pattern and not pattern.match(api_key):
        return TestKeyResponse(
            valid=False,
            message=f"Key format looks wrong for {provider}. Check that you copied the full key.",
        )

    # Make a minimal live call to verify the key actually works
    try:
        if provider == "gemini":
            model_str = "gemini/gemini-2.5-flash"
            await _test_gemini_key(api_key, model_str)
        elif provider == "openai":
            await _test_openai_key(api_key)
        elif provider == "anthropic":
            await _test_anthropic_key(api_key)
        else:
            return TestKeyResponse(valid=False, message=f"Unknown provider: {provider}")
    except Exception as exc:
        msg = str(exc)
        logger.info("Key test failed for provider=%s user=%s: %s", provider, user.id, msg)
        # Surface a friendly error without leaking internals
        if "401" in msg or "Unauthorized" in msg or "authentication" in msg.lower():
            return TestKeyResponse(valid=False, message="Key rejected — invalid credentials.")
        if "403" in msg or "permission" in msg.lower():
            return TestKeyResponse(valid=False, message="Key lacks required permissions.")
        if "quota" in msg.lower() or "429" in msg:
            # Key is valid but quota exhausted — treat as valid
            return TestKeyResponse(valid=True, message="Key is valid (quota currently exhausted).")
        return TestKeyResponse(valid=False, message=f"Could not verify key: {msg[:120]}")

    return TestKeyResponse(valid=True, message="Key verified successfully.")


# -----------------------------------------------------------------
# Key-testing helpers (minimal calls)
# -----------------------------------------------------------------


async def _test_gemini_key(api_key: str, model: str) -> None:
    """Send a 1-token prompt to Gemini to confirm the key works."""
    import httpx

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": "Hi"}]}],
        "generationConfig": {"maxOutputTokens": 1},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
    if resp.status_code == 400:
        # 400 with a real key usually means bad request shape — key is fine
        return
    resp.raise_for_status()


async def _test_openai_key(api_key: str) -> None:
    """List OpenAI models — cheap way to verify the key."""
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    resp.raise_for_status()


async def _test_anthropic_key(api_key: str) -> None:
    """Send a 1-token prompt to Anthropic to confirm the key works."""
    import httpx

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "Hi"}],
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
    resp.raise_for_status()
