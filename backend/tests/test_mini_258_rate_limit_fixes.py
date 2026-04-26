"""Tests for MINI-258: rate-limit fixes for landing page 503.

Covers:
- GET /api/minis and GET /api/minis/promo are in _SKIP_PATHS (no rate limiting)
- IPRateLimitMiddleware fails open (returns 200, not 503) when the DB store raises
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestSkipPathsContainMiniEndpoints:
    """_SKIP_PATHS must include the public read-only mini list endpoints."""

    def test_api_minis_in_skip_paths(self):
        from app.middleware.ip_rate_limit import _SKIP_PATHS

        assert "/api/minis" in _SKIP_PATHS, (
            "GET /api/minis must be skipped — Vercel SSR shares IPs and this endpoint "
            "has no LLM cost (MINI-258)"
        )

    def test_api_minis_promo_in_skip_paths(self):
        from app.middleware.ip_rate_limit import _SKIP_PATHS

        assert "/api/minis/promo" in _SKIP_PATHS, (
            "GET /api/minis/promo must be skipped — it's the landing page promo card "
            "endpoint and must never be rate-limited by IP (MINI-258)"
        )

    def test_health_still_in_skip_paths(self):
        from app.middleware.ip_rate_limit import _SKIP_PATHS

        assert "/api/health" in _SKIP_PATHS


class TestMiddlewareFailsOpenOnStoreError:
    """When the rate-limit store raises, the middleware must fail open (not 503)."""

    @pytest.mark.asyncio
    async def test_store_exception_passes_request_through(self):
        """If store.hit() raises, the middleware calls call_next and returns its response."""
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        from app.middleware.ip_rate_limit import IPRateLimitMiddleware

        # Build a mock store that always raises
        bad_store = MagicMock()
        bad_store.hit = AsyncMock(side_effect=RuntimeError("DB down"))

        middleware = IPRateLimitMiddleware(MagicMock(), store=bad_store)

        # Craft a minimal ASGI-compatible request for /api/minis (POST so it's not skipped)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/some-endpoint",
            "query_string": b"",
            "headers": [],
            "client": ("10.0.0.1", 12345),
        }
        request = Request(scope)

        good_response = JSONResponse({"ok": True}, status_code=200)
        call_next = AsyncMock(return_value=good_response)

        response = await middleware.dispatch(request, call_next)

        # Must NOT be a 503 — should be the downstream response
        assert response.status_code == 200
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_exception_does_not_return_503(self):
        """The old behaviour returned 503 on store failure — this must no longer happen."""
        from starlette.requests import Request

        from app.middleware.ip_rate_limit import IPRateLimitMiddleware

        bad_store = MagicMock()
        bad_store.hit = AsyncMock(side_effect=ConnectionError("Neon hiccup"))

        middleware = IPRateLimitMiddleware(MagicMock(), store=bad_store)

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/minis/alliecatowo",
            "query_string": b"",
            "headers": [],
            "client": ("10.0.0.2", 9999),
        }
        request = Request(scope)

        from starlette.responses import Response

        downstream = Response(content=b"ok", status_code=200)
        call_next = AsyncMock(return_value=downstream)

        response = await middleware.dispatch(request, call_next)

        assert response.status_code != 503, (
            "Middleware must not return 503 when the rate-limit store is unavailable; "
            "it should fail open so a transient DB hiccup does not kill the landing page"
        )
