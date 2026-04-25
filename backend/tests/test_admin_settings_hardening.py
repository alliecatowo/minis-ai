"""Regression tests for MINI-113 admin authorization hardening."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


def _user(username: str | None = "regularuser"):
    return SimpleNamespace(
        id="user-1",
        github_username=username,
        display_name="Regular User",
        avatar_url=None,
    )


def _settings_row(*, is_admin: bool = False, llm_api_key: str | None = None):
    return SimpleNamespace(
        llm_provider="gemini",
        preferred_model=None,
        llm_api_key=llm_api_key,
        is_admin=is_admin,
        model_preferences=None,
    )


def test_update_settings_rejects_is_admin_payload():
    """Users cannot submit admin state through the mutable settings API."""
    from app.routes.settings import UpdateSettingsRequest

    with pytest.raises(ValidationError):
        UpdateSettingsRequest(llm_provider="openai", is_admin=True)


def test_settings_response_ignores_legacy_is_admin_flag_for_non_admin():
    """A stored user_settings.is_admin=True row must not grant admin status."""
    from app.routes.settings import _build_settings_response

    with patch("app.core.admin.settings") as mock_settings:
        mock_settings.admin_username_list = ["trustedadmin"]

        response = _build_settings_response(_settings_row(is_admin=True), _user("regularuser"))

    assert response.is_admin is False


def test_settings_response_uses_explicit_admin_allowlist():
    """The real dev/test admin path is the server-side ADMIN_USERNAMES allowlist."""
    from app.routes.settings import _build_settings_response

    with patch("app.core.admin.settings") as mock_settings:
        mock_settings.admin_username_list = ["trustedadmin"]

        response = _build_settings_response(_settings_row(is_admin=False), _user("TrustedAdmin"))

    assert response.is_admin is True


@pytest.mark.asyncio
async def test_settings_usage_ignores_legacy_is_admin_exemption():
    """A self-escalated settings row must not make the user exempt from usage limits."""
    from app.routes.settings import get_usage

    user_settings_result = MagicMock()
    user_settings_result.scalar_one_or_none.return_value = _settings_row(is_admin=True)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[user_settings_result, count_result, count_result])

    with patch("app.core.admin.settings") as mock_settings:
        mock_settings.admin_username_list = ["trustedadmin"]

        response = await get_usage(user=_user("regularuser"), session=session)

    assert response.is_exempt is False


@pytest.mark.asyncio
async def test_settings_usage_preserves_byok_exemption():
    """BYOK remains a non-admin usage exemption."""
    from app.routes.settings import get_usage

    user_settings_result = MagicMock()
    user_settings_result.scalar_one_or_none.return_value = _settings_row(llm_api_key="encrypted")
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[user_settings_result, count_result, count_result])

    with patch("app.core.admin.settings") as mock_settings:
        mock_settings.admin_username_list = []

        response = await get_usage(user=_user("regularuser"), session=session)

    assert response.is_exempt is True


def test_admin_endpoints_fail_closed_without_trusted_username():
    """Admin-only endpoints return 403 when no trusted username claim is present."""
    from app.routes.usage import _require_admin

    with pytest.raises(HTTPException) as exc_info:
        _require_admin(_user(username=None))

    assert exc_info.value.status_code == 403


def test_admin_endpoints_use_explicit_admin_allowlist():
    """Configured GitHub usernames remain the explicit admin path."""
    from app.routes.usage import _require_admin

    with patch("app.core.admin.settings") as mock_settings:
        mock_settings.admin_username_list = ["trustedadmin"]

        _require_admin(_user("TrustedAdmin"))
