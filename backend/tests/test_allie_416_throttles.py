"""Tests for ALLIE-416: per-IP throttle on mini creation + progress SSE."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(github_username: str | None = None, display_name: str | None = None):
    return SimpleNamespace(github_username=github_username, display_name=display_name)


def _fresh_windows():
    """Clear shared _windows dict before each test."""
    from app.middleware import ip_rate_limit

    ip_rate_limit._windows.clear()


# ---------------------------------------------------------------------------
# 1. Mini-create per-IP hourly throttle
# ---------------------------------------------------------------------------


class TestMiniCreateIpThrottle:
    """Tests for check_mini_create_ip_limit()."""

    def test_first_request_allowed(self):
        """First create from an IP is allowed."""
        _fresh_windows()
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 2

        non_admin = _make_user(github_username="regulardev")
        admin_list = ["alliecatowo"]

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with patch("app.core.rate_limit.settings") as mock_rl:
                    mock_rl.admin_username_list = admin_list
                    # Should not raise
                    check_mini_create_ip_limit("10.0.0.1", user=non_admin)

    def test_third_request_returns_429(self):
        """3rd mini-create from the same IP within an hour returns 429."""
        _fresh_windows()
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 2

        non_admin = _make_user(github_username="regulardev")
        admin_list = ["alliecatowo"]

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with patch("app.core.rate_limit.settings") as mock_rl:
                    mock_rl.admin_username_list = admin_list
                    # First two should pass
                    check_mini_create_ip_limit("10.0.0.2", user=non_admin)
                    check_mini_create_ip_limit("10.0.0.2", user=non_admin)

                    # Third should be blocked
                    with pytest.raises(HTTPException) as exc_info:
                        check_mini_create_ip_limit("10.0.0.2", user=non_admin)
                    assert exc_info.value.status_code == 429
                    assert "Retry-After" in exc_info.value.headers

    def test_retry_after_header_is_positive(self):
        """Retry-After value is a positive integer."""
        _fresh_windows()
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 1

        non_admin = _make_user(github_username="regulardev")
        admin_list = ["alliecatowo"]

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with patch("app.core.rate_limit.settings") as mock_rl:
                    mock_rl.admin_username_list = admin_list
                    check_mini_create_ip_limit("10.0.0.3", user=non_admin)  # first — passes

                    with pytest.raises(HTTPException) as exc_info:
                        check_mini_create_ip_limit("10.0.0.3", user=non_admin)  # second — 429

                    retry_after = int(exc_info.value.headers["Retry-After"])
                    assert retry_after >= 1

    def test_admin_bypasses_create_throttle(self):
        """Admin users bypass the per-IP mini creation throttle."""
        _fresh_windows()
        from app.middleware import ip_rate_limit
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 1  # very low

        admin = _make_user(github_username="alliecatowo")
        admin_list = ["alliecatowo"]

        # Pre-fill window beyond limit
        ip = "10.0.0.4"
        now = time.monotonic()
        ip_rate_limit._windows[f"create:{ip}"] = [now - 100] * 10

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with patch("app.core.rate_limit.settings") as mock_rl:
                    mock_rl.admin_username_list = admin_list
                    # Should NOT raise — admin bypass
                    check_mini_create_ip_limit(ip, user=admin)

    def test_different_ips_have_independent_windows(self):
        """Two different IPs each get their own independent window."""
        _fresh_windows()
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 2

        non_admin = _make_user(github_username="regulardev")
        admin_list = ["alliecatowo"]

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with patch("app.core.rate_limit.settings") as mock_rl:
                    mock_rl.admin_username_list = admin_list
                    # IP A exhausts its limit
                    check_mini_create_ip_limit("10.0.1.1", user=non_admin)
                    check_mini_create_ip_limit("10.0.1.1", user=non_admin)

                    # IP B should still be fine
                    check_mini_create_ip_limit("10.0.1.2", user=non_admin)

    def test_create_key_does_not_collide_with_chat_key(self):
        """create: key space is independent from chat: key space."""
        _fresh_windows()
        from app.middleware import ip_rate_limit
        from app.middleware.ip_rate_limit import check_mini_create_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_create_ip_hourly_limit = 2

        non_admin = _make_user(github_username="regulardev")
        admin_list = ["alliecatowo"]

        # Pre-fill chat keys to the limit — should NOT affect create limit
        ip = "10.0.0.5"
        now = time.monotonic()
        ip_rate_limit._windows[f"chat:{ip}:mini-abc:hourly"] = [now - 100] * 20

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with patch("app.core.rate_limit.settings") as mock_rl:
                    mock_rl.admin_username_list = admin_list
                    # create: key is fresh, so it should pass
                    check_mini_create_ip_limit(ip, user=non_admin)


# ---------------------------------------------------------------------------
# 2. SSE progress per-IP per-minute throttle
# ---------------------------------------------------------------------------


class TestMiniSseIpThrottle:
    """Tests for check_mini_sse_ip_limit()."""

    def test_first_connection_allowed(self):
        """First SSE connection from an IP is allowed."""
        _fresh_windows()
        from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_sse_ip_per_min_limit = 10

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                check_mini_sse_ip_limit("192.168.1.1")  # should not raise

    def test_eleventh_connection_returns_429(self):
        """11th new SSE connection from the same IP within a minute returns 429."""
        _fresh_windows()
        from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_sse_ip_per_min_limit = 10

        ip = "192.168.1.2"

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                # First 10 should pass
                for _ in range(10):
                    check_mini_sse_ip_limit(ip)

                # 11th should be blocked
                with pytest.raises(HTTPException) as exc_info:
                    check_mini_sse_ip_limit(ip)
                assert exc_info.value.status_code == 429
                assert "Retry-After" in exc_info.value.headers

    def test_sse_retry_after_header_is_positive(self):
        """SSE 429 carries a positive Retry-After header."""
        _fresh_windows()
        from app.middleware import ip_rate_limit
        from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_sse_ip_per_min_limit = 3

        ip = "192.168.1.3"
        now = time.monotonic()
        # Pre-fill window at the limit
        ip_rate_limit._windows[f"sse:{ip}"] = [now - 10] * 3

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                with pytest.raises(HTTPException) as exc_info:
                    check_mini_sse_ip_limit(ip)

                retry_after = int(exc_info.value.headers["Retry-After"])
                assert retry_after >= 1

    def test_sse_different_ips_are_independent(self):
        """Different IPs have separate SSE connection windows."""
        _fresh_windows()
        from app.middleware import ip_rate_limit
        from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_sse_ip_per_min_limit = 2

        now = time.monotonic()
        # Exhaust limit for IP A
        ip_a = "192.168.2.1"
        ip_rate_limit._windows[f"sse:{ip_a}"] = [now - 10] * 2

        ip_b = "192.168.2.2"

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                # IP A should be blocked
                with pytest.raises(HTTPException) as exc_info:
                    check_mini_sse_ip_limit(ip_a)
                assert exc_info.value.status_code == 429

                # IP B should still be fine
                check_mini_sse_ip_limit(ip_b)  # should not raise

    def test_sse_key_does_not_collide_with_create_or_chat(self):
        """sse: key space is independent from create: and chat: key spaces."""
        _fresh_windows()
        from app.middleware import ip_rate_limit
        from app.middleware.ip_rate_limit import check_mini_sse_ip_limit

        mock_settings = MagicMock()
        mock_settings.mini_sse_ip_per_min_limit = 10

        ip = "192.168.1.4"
        now = time.monotonic()
        # Fill create and chat keys — should not affect sse: key
        ip_rate_limit._windows[f"create:{ip}"] = [now - 10] * 10
        ip_rate_limit._windows[f"chat:{ip}:mini-x:burst"] = [now - 10] * 10

        with patch("app.middleware.ip_rate_limit.settings", mock_settings, create=True):
            with patch("app.core.config.settings", mock_settings):
                # sse: key is fresh — should pass
                check_mini_sse_ip_limit(ip)


# ---------------------------------------------------------------------------
# 3. Settings defaults
# ---------------------------------------------------------------------------


class TestAllie416Settings:
    def test_mini_create_ip_hourly_limit_default(self):
        """Default mini_create_ip_hourly_limit is 2."""
        from app.core.config import Settings

        s = Settings()
        assert s.mini_create_ip_hourly_limit == 2

    def test_mini_sse_ip_per_min_limit_default(self):
        """Default mini_sse_ip_per_min_limit is 10."""
        from app.core.config import Settings

        s = Settings()
        assert s.mini_sse_ip_per_min_limit == 10

    def test_mini_create_ip_hourly_limit_env_override(self):
        """MINI_CREATE_IP_HOURLY_LIMIT env var overrides the default."""
        from app.core.config import Settings

        s = Settings(mini_create_ip_hourly_limit=5)
        assert s.mini_create_ip_hourly_limit == 5

    def test_mini_sse_ip_per_min_limit_env_override(self):
        """MINI_SSE_IP_PER_MIN_LIMIT env var overrides the default."""
        from app.core.config import Settings

        s = Settings(mini_sse_ip_per_min_limit=20)
        assert s.mini_sse_ip_per_min_limit == 20
