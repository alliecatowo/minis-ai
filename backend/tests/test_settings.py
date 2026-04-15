"""Tests for settings routes: test-key, models/tiers, model_preferences (ALLIE-301)."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Key format validator tests
# ---------------------------------------------------------------------------

class TestKeyFormatValidation:
    """Validate the regex patterns used in the test-key endpoint."""

    def setup_method(self):
        from app.routes.settings import _KEY_PATTERNS
        self.patterns = _KEY_PATTERNS

    def test_gemini_valid_key(self):
        key = "AIzaSyD" + "a" * 35
        assert self.patterns["gemini"].match(key)

    def test_gemini_short_key_rejected(self):
        assert not self.patterns["gemini"].match("AIzaSy_short")

    def test_gemini_wrong_prefix_rejected(self):
        assert not self.patterns["gemini"].match("sk-" + "a" * 40)

    def test_openai_valid_key(self):
        key = "sk-" + "a" * 40
        assert self.patterns["openai"].match(key)

    def test_openai_short_key_rejected(self):
        assert not self.patterns["openai"].match("sk-short")

    def test_openai_wrong_prefix_rejected(self):
        assert not self.patterns["openai"].match("AIza" + "a" * 40)

    def test_anthropic_valid_key(self):
        key = "sk-ant-api03-" + "a" * 40
        assert self.patterns["anthropic"].match(key)

    def test_anthropic_short_key_rejected(self):
        assert not self.patterns["anthropic"].match("sk-ant-short")

    def test_anthropic_wrong_prefix_rejected(self):
        assert not self.patterns["anthropic"].match("sk-" + "a" * 40)


# ---------------------------------------------------------------------------
# TIER_MODELS structure tests
# ---------------------------------------------------------------------------

class TestTierModelsStructure:
    def setup_method(self):
        from app.routes.settings import TIER_MODELS
        self.tier_models = TIER_MODELS

    def test_all_providers_present(self):
        assert "gemini" in self.tier_models
        assert "openai" in self.tier_models
        assert "anthropic" in self.tier_models

    def test_all_tiers_present_for_each_provider(self):
        for provider, tiers in self.tier_models.items():
            assert "fast" in tiers, f"{provider} missing 'fast' tier"
            assert "standard" in tiers, f"{provider} missing 'standard' tier"
            assert "thinking" in tiers, f"{provider} missing 'thinking' tier"

    def test_each_tier_has_at_least_one_model(self):
        for provider, tiers in self.tier_models.items():
            for tier, models in tiers.items():
                assert len(models) >= 1, f"{provider}/{tier} has no models"

    def test_each_model_has_id_and_name(self):
        for provider, tiers in self.tier_models.items():
            for tier, models in tiers.items():
                for m in models:
                    assert "id" in m, f"{provider}/{tier} model missing 'id'"
                    assert "name" in m, f"{provider}/{tier} model missing 'name'"
                    assert m["id"], f"{provider}/{tier} model has empty 'id'"
                    assert m["name"], f"{provider}/{tier} model has empty 'name'"


# ---------------------------------------------------------------------------
# TierModelsResponse schema tests
# ---------------------------------------------------------------------------

class TestTierModelsEndpointResponse:
    """Test the structure returned by get_tier_models (no DB needed)."""

    @pytest.mark.asyncio
    async def test_get_tier_models_structure(self):
        from app.routes.settings import get_tier_models

        result = await get_tier_models()

        assert hasattr(result, "providers")
        assert hasattr(result, "tiers")
        assert hasattr(result, "defaults")

    @pytest.mark.asyncio
    async def test_tiers_list(self):
        from app.routes.settings import get_tier_models

        result = await get_tier_models()
        assert set(result.tiers) == {"fast", "standard", "thinking"}

    @pytest.mark.asyncio
    async def test_defaults_present_for_all_providers(self):
        from app.routes.settings import get_tier_models

        result = await get_tier_models()
        for provider in ["gemini", "openai", "anthropic"]:
            assert provider in result.defaults, f"Missing defaults for {provider}"

    @pytest.mark.asyncio
    async def test_defaults_cover_all_tiers(self):
        from app.routes.settings import get_tier_models

        result = await get_tier_models()
        for provider, tier_defaults in result.defaults.items():
            for tier in ["fast", "standard", "thinking"]:
                assert tier in tier_defaults, f"{provider} missing default for {tier}"


# ---------------------------------------------------------------------------
# TestKeyResponse logic tests
# ---------------------------------------------------------------------------

class TestTestKeyResponseLogic:
    """Test the test-key helper path logic without hitting live APIs."""

    @pytest.mark.asyncio
    async def test_unknown_provider_returns_invalid(self):
        from app.routes.settings import test_api_key, TestKeyRequest

        user = MagicMock()
        user.id = "user-1"
        body = TestKeyRequest(api_key="some-key", provider="unknown_provider")

        result = await test_api_key(body, user=user)
        assert result.valid is False
        assert "Unknown provider" in result.message

    @pytest.mark.asyncio
    async def test_bad_format_gemini_returns_invalid(self):
        from app.routes.settings import test_api_key, TestKeyRequest

        user = MagicMock()
        user.id = "user-1"
        body = TestKeyRequest(api_key="bad-key-format", provider="gemini")

        result = await test_api_key(body, user=user)
        assert result.valid is False
        assert "format" in result.message.lower()

    @pytest.mark.asyncio
    async def test_bad_format_openai_returns_invalid(self):
        from app.routes.settings import test_api_key, TestKeyRequest

        user = MagicMock()
        user.id = "user-1"
        body = TestKeyRequest(api_key="bad-key-format", provider="openai")

        result = await test_api_key(body, user=user)
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_bad_format_anthropic_returns_invalid(self):
        from app.routes.settings import test_api_key, TestKeyRequest

        user = MagicMock()
        user.id = "user-1"
        body = TestKeyRequest(api_key="bad-key-format", provider="anthropic")

        result = await test_api_key(body, user=user)
        assert result.valid is False

    @pytest.mark.asyncio
    async def test_quota_exceeded_treated_as_valid(self):
        """A 429 / quota error means the key is real but exhausted."""
        from app.routes.settings import test_api_key, TestKeyRequest

        user = MagicMock()
        user.id = "user-1"
        # Use a well-formatted key so it passes format check
        api_key = "AIzaSyD" + "b" * 35
        body = TestKeyRequest(api_key=api_key, provider="gemini")

        with patch(
            "app.routes.settings._test_gemini_key",
            new_callable=AsyncMock,
            side_effect=Exception("quota exceeded 429"),
        ):
            result = await test_api_key(body, user=user)

        assert result.valid is True
        assert "quota" in result.message.lower()

    @pytest.mark.asyncio
    async def test_401_treated_as_invalid(self):
        """A 401 means wrong credentials."""
        from app.routes.settings import test_api_key, TestKeyRequest

        user = MagicMock()
        user.id = "user-1"
        api_key = "AIzaSyD" + "c" * 35
        body = TestKeyRequest(api_key=api_key, provider="gemini")

        with patch(
            "app.routes.settings._test_gemini_key",
            new_callable=AsyncMock,
            side_effect=Exception("401 Unauthorized"),
        ):
            result = await test_api_key(body, user=user)

        assert result.valid is False
        assert "invalid" in result.message.lower() or "rejected" in result.message.lower()

    @pytest.mark.asyncio
    async def test_successful_gemini_test(self):
        """When the live call succeeds, return valid=True."""
        from app.routes.settings import test_api_key, TestKeyRequest

        user = MagicMock()
        user.id = "user-1"
        api_key = "AIzaSyD" + "d" * 35
        body = TestKeyRequest(api_key=api_key, provider="gemini")

        with patch(
            "app.routes.settings._test_gemini_key",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await test_api_key(body, user=user)

        assert result.valid is True

    @pytest.mark.asyncio
    async def test_successful_openai_test(self):
        from app.routes.settings import test_api_key, TestKeyRequest

        user = MagicMock()
        user.id = "user-1"
        api_key = "sk-" + "e" * 40
        body = TestKeyRequest(api_key=api_key, provider="openai")

        with patch(
            "app.routes.settings._test_openai_key",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await test_api_key(body, user=user)

        assert result.valid is True

    @pytest.mark.asyncio
    async def test_successful_anthropic_test(self):
        from app.routes.settings import test_api_key, TestKeyRequest

        user = MagicMock()
        user.id = "user-1"
        api_key = "sk-ant-api03-" + "f" * 40
        body = TestKeyRequest(api_key=api_key, provider="anthropic")

        with patch(
            "app.routes.settings._test_anthropic_key",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await test_api_key(body, user=user)

        assert result.valid is True


# ---------------------------------------------------------------------------
# UpdateSettingsRequest model_preferences field
# ---------------------------------------------------------------------------

class TestUpdateSettingsRequestSchema:
    def test_model_preferences_accepted(self):
        from app.routes.settings import UpdateSettingsRequest

        req = UpdateSettingsRequest(
            llm_provider="openai",
            model_preferences={"fast": "openai:gpt-4.1-mini", "standard": "openai:gpt-4.1"},
        )
        assert req.model_preferences == {
            "fast": "openai:gpt-4.1-mini",
            "standard": "openai:gpt-4.1",
        }

    def test_model_preferences_optional(self):
        from app.routes.settings import UpdateSettingsRequest

        req = UpdateSettingsRequest(llm_provider="gemini")
        assert req.model_preferences is None

    def test_model_preferences_none_explicit(self):
        from app.routes.settings import UpdateSettingsRequest

        req = UpdateSettingsRequest(model_preferences=None)
        assert req.model_preferences is None


# ---------------------------------------------------------------------------
# SettingsResponse includes model_preferences
# ---------------------------------------------------------------------------

class TestSettingsResponseSchema:
    def test_includes_model_preferences(self):
        from app.routes.settings import SettingsResponse

        resp = SettingsResponse(
            llm_provider="anthropic",
            preferred_model=None,
            has_api_key=True,
            is_admin=False,
            model_preferences={"fast": "anthropic:claude-haiku-4-5"},
        )
        assert resp.model_preferences == {"fast": "anthropic:claude-haiku-4-5"}

    def test_model_preferences_defaults_to_none(self):
        from app.routes.settings import SettingsResponse

        resp = SettingsResponse(
            llm_provider="gemini",
            preferred_model=None,
            has_api_key=False,
            is_admin=False,
        )
        assert resp.model_preferences is None
