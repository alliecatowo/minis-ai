"""Unit tests for rate_limit admin bypass logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.rate_limit import _is_admin_user


# ---------------------------------------------------------------------------
# _is_admin_user helpers
# ---------------------------------------------------------------------------


def _make_user(github_username: str | None = None, display_name: str | None = None):
    """Return a lightweight namespace that mimics the User ORM model fields."""
    return SimpleNamespace(github_username=github_username, display_name=display_name)


ADMIN_LIST = ["alliecatowo", "devadmin"]


@pytest.fixture(autouse=True)
def patch_admin_list():
    """Patch settings.admin_username_list to a fixed list for all tests."""
    with patch("app.core.admin.settings") as mock_settings:
        mock_settings.admin_username_list = ADMIN_LIST
        yield mock_settings


class TestIsAdminUser:
    def test_exact_github_username_match(self):
        user = _make_user(github_username="alliecatowo")
        assert _is_admin_user(user) is True

    def test_case_insensitive_github_username(self):
        user = _make_user(github_username="AllieCatOwO")
        assert _is_admin_user(user) is True

    def test_whitespace_stripped_github_username(self):
        user = _make_user(github_username="  alliecatowo  ")
        assert _is_admin_user(user) is True

    def test_display_name_does_not_grant_admin_when_github_username_is_null(self):
        """Display names are mutable and must not grant trusted admin bypass."""
        user = _make_user(github_username=None, display_name="alliecatowo")
        assert _is_admin_user(user) is False

    def test_display_name_does_not_grant_admin_case_insensitive(self):
        user = _make_user(github_username=None, display_name="ALLIECATOWO")
        assert _is_admin_user(user) is False

    def test_non_admin_user_not_bypassed(self):
        user = _make_user(github_username="randomdev")
        assert _is_admin_user(user) is False

    def test_non_admin_null_both_fields(self):
        user = _make_user(github_username=None, display_name=None)
        assert _is_admin_user(user) is False

    def test_none_user_returns_false(self):
        assert _is_admin_user(None) is False

    def test_second_admin_in_list(self):
        user = _make_user(github_username="devadmin")
        assert _is_admin_user(user) is True


# ---------------------------------------------------------------------------
# check_rate_limit integration — admin bypass short-circuits enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_rate_limit_admin_bypasses_enforcement():
    """Admin user should return without raising even if event count is at limit."""
    from app.core.rate_limit import check_rate_limit

    session = AsyncMock()

    # First execute call: UserSettings lookup → no row
    user_settings_result = MagicMock()
    user_settings_result.scalar_one_or_none.return_value = None

    # Second execute call: User lookup → admin user
    admin_user = _make_user(github_username="alliecatowo")
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = admin_user

    session.execute.side_effect = [user_settings_result, user_result]

    # Should NOT raise even though we never get to the count query
    await check_rate_limit("some-user-id", "mini_create", session)


@pytest.mark.asyncio
async def test_check_rate_limit_non_admin_enforced():
    """Non-admin user hitting the limit should get a 429."""
    from fastapi import HTTPException

    from app.core.rate_limit import check_rate_limit

    import datetime

    session = AsyncMock()

    # UserSettings → no row
    user_settings_result = MagicMock()
    user_settings_result.scalar_one_or_none.return_value = None

    # User lookup → non-admin
    regular_user = _make_user(github_username="randomdev")
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = regular_user

    # Count query → at limit (1 for mini_create)
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    # Oldest event query
    oldest_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=12)
    oldest_result = MagicMock()
    oldest_result.scalar_one.return_value = oldest_time

    session.execute.side_effect = [user_settings_result, user_result, count_result, oldest_result]

    with pytest.raises(HTTPException) as exc_info:
        await check_rate_limit("other-user-id", "mini_create", session)

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_check_rate_limit_ignores_user_settings_admin_flag():
    """A mutable user_settings.is_admin=True row must not bypass rate limits."""
    from fastapi import HTTPException

    from app.core.rate_limit import check_rate_limit
    from app.models.user_settings import UserSettings

    import datetime

    session = AsyncMock()

    user_settings_result = MagicMock()
    user_settings_result.scalar_one_or_none.return_value = UserSettings(
        user_id="self-edited-user",
        is_admin=True,
    )

    regular_user = _make_user(github_username="randomdev")
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = regular_user

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    oldest_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=12)
    oldest_result = MagicMock()
    oldest_result.scalar_one.return_value = oldest_time

    session.execute.side_effect = [user_settings_result, user_result, count_result, oldest_result]

    with pytest.raises(HTTPException) as exc_info:
        await check_rate_limit("self-edited-user", "mini_create", session)

    assert exc_info.value.status_code == 429
