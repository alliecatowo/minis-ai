"""IP-based sliding window rate limiting middleware.

Uses the shared database-backed sliding-window limiter so request controls
survive deploys and are enforced across app instances.
Applies different limits based on request context:
- Unauthenticated requests: 60 req/min per IP
- Authenticated requests: 300 req/min per user
- Auth endpoints: 10 attempts/min per IP

Also exposes check functions for LLM-backed endpoints:

``check_chat_ip_mini_limit()`` — per-IP + per-mini chat throttle:
- Hourly window: configurable via ``CHAT_IP_MINI_HOURLY_LIMIT`` (default 20)
- Burst window: configurable via ``CHAT_IP_MINI_BURST_LIMIT`` (default 5/min)
- Admin bypass: checked via ``_is_admin_user()`` from rate_limit module

``check_mini_create_ip_limit()`` — per-IP mini creation throttle (ALLIE-416):
- 2 creates per IP per hour (configurable via ``MINI_CREATE_IP_HOURLY_LIMIT``)
- Key prefix: ``create:`` to avoid colliding with chat keys
- Admin bypass via same ``_is_admin_user()`` helper

``check_mini_sse_ip_limit()`` — per-IP SSE progress stream throttle (ALLIE-416):
- 10 new connections per IP per minute (configurable via ``MINI_SSE_IP_PER_MIN_LIMIT``)
- Key prefix: ``sse:`` to avoid colliding with other keys
- Rate-limits new connections; does not track concurrent streams
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.persistent_rate_limit import (
    SlidingRateLimitStore,
    get_default_rate_limit_store,
)

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

# Limits: (max_requests, window_seconds)
UNAUTH_LIMIT = (60, 60)  # 60 req/min per IP
AUTH_LIMIT = (300, 60)  # 300 req/min per user
AUTH_ENDPOINT_LIMIT = (10, 60)  # 10 attempts/min per IP

_AUTH_PATHS = frozenset(
    {
        "/api/auth/login",
        "/api/auth/callback",
        "/api/auth/token",
        "/api/auth/refresh",
    }
)

# Paths to skip (health checks, static assets, and public read-only endpoints that
# must not be rate-limited by the sliding-window store — e.g. Vercel shares outbound
# IPs so all SSR requests appear as the same unauthenticated IP, and
# GET /api/minis / GET /api/minis/promo carry no LLM cost).
_SKIP_PATHS = frozenset(
    {
        "/api/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        # Public read-only mini listing — landing page promo card depends on this.
        # No auth, no LLM, no side-effects; rate-limiting by IP would block Vercel
        # SSR traffic that shares outbound addresses (MINI-258).
        "/api/minis",
        "/api/minis/promo",
    }
)

# ── Per-IP + per-mini chat throttle (ALLIE-405) ─────────────────────────────


def _storage_unavailable_exception():
    from fastapi import HTTPException

    return HTTPException(
        status_code=503,
        detail="Rate limit storage unavailable; request blocked for safety.",
    )


async def check_chat_ip_mini_limit(
    ip: str,
    mini_id: str,
    user: object | None = None,
    *,
    store: SlidingRateLimitStore | None = None,
) -> None:
    """Apply per-IP + per-mini sliding window limits to the chat endpoint.

    Two windows are checked:
    - Burst: ``CHAT_IP_MINI_BURST_LIMIT`` requests per minute
    - Hourly: ``CHAT_IP_MINI_HOURLY_LIMIT`` requests per hour

    Admin users (checked via ``_is_admin_user``) bypass both limits.

    Raises:
        fastapi.HTTPException: 429 with ``Retry-After`` header when the limit
            is exceeded.
    """
    from fastapi import HTTPException

    from app.core.config import settings as _settings
    from app.core.rate_limit import _is_admin_user

    if _is_admin_user(user):
        logger.info("chat_throttle bypass for admin user ip=%s mini_id=%s", ip, mini_id)
        return

    hourly_limit = _settings.chat_ip_mini_hourly_limit
    burst_limit = _settings.chat_ip_mini_burst_limit

    limiter = store or get_default_rate_limit_store()
    base_key = f"chat:{ip}:{mini_id}"
    burst_key = f"{base_key}:burst"
    hourly_key = f"{base_key}:hourly"

    # Check burst first (stricter, smaller window)
    try:
        burst_decision = await limiter.hit(burst_key, burst_limit, 60)
    except Exception as exc:
        logger.exception("chat_throttle persistent store unavailable")
        raise _storage_unavailable_exception() from exc
    if not burst_decision.allowed:
        retry_after = burst_decision.retry_after or 60
        logger.warning(
            "chat_throttle burst exceeded ip=%s mini_id=%s limit=%d/min",
            ip,
            mini_id,
            burst_limit,
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Chat rate limit exceeded: {burst_limit} messages per minute. "
                f"Please wait {retry_after}s before retrying."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    # Check hourly window
    try:
        hourly_decision = await limiter.hit(hourly_key, hourly_limit, 3600)
    except Exception as exc:
        logger.exception("chat_throttle persistent store unavailable")
        raise _storage_unavailable_exception() from exc
    if not hourly_decision.allowed:
        retry_after = hourly_decision.retry_after or 3600
        logger.warning(
            "chat_throttle hourly exceeded ip=%s mini_id=%s limit=%d/hour",
            ip,
            mini_id,
            hourly_limit,
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Chat rate limit exceeded: {hourly_limit} messages per hour per mini. "
                f"Please wait {retry_after}s before retrying."
            ),
            headers={"Retry-After": str(retry_after)},
        )


# ── Per-IP mini creation throttle (ALLIE-416) ───────────────────────────────


async def check_mini_create_ip_limit(
    ip: str,
    user: object | None = None,
    *,
    store: SlidingRateLimitStore | None = None,
) -> None:
    """Apply a per-IP hourly limit to POST /api/minis (mini creation).

    Limit: ``MINI_CREATE_IP_HOURLY_LIMIT`` creates per hour per IP (default 2).
    Admin users bypass the limit.

    Key prefix: ``create:`` — does not collide with chat throttle keys.

    Raises:
        fastapi.HTTPException: 429 with ``Retry-After`` header when the limit
            is exceeded.
    """
    from fastapi import HTTPException

    from app.core.config import settings as _settings
    from app.core.rate_limit import _is_admin_user

    if _is_admin_user(user):
        logger.info("mini_create_throttle bypass for admin user ip=%s", ip)
        return

    hourly_limit = _settings.mini_create_ip_hourly_limit
    key = f"create:{ip}"
    limiter = store or get_default_rate_limit_store()

    try:
        decision = await limiter.hit(key, hourly_limit, 3600)
    except Exception as exc:
        logger.exception("mini_create_throttle persistent store unavailable")
        raise _storage_unavailable_exception() from exc
    if not decision.allowed:
        retry_after = decision.retry_after or 3600
        logger.warning(
            "mini_create_throttle exceeded ip=%s limit=%d/hour",
            ip,
            hourly_limit,
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Mini creation rate limit exceeded: {hourly_limit} creations per hour per IP. "
                f"Please wait {retry_after}s before retrying."
            ),
            headers={"Retry-After": str(retry_after)},
        )


# ── Per-IP SSE connection throttle (ALLIE-416) ──────────────────────────────


async def check_mini_sse_ip_limit(
    ip: str,
    *,
    store: SlidingRateLimitStore | None = None,
) -> None:
    """Apply a per-IP per-minute rate limit on new SSE progress connections.

    Limit: ``MINI_SSE_IP_PER_MIN_LIMIT`` new connections per IP per minute
    (default 10).  This prevents a flood of new SSE connections from burning
    compute, while still allowing legitimate polling during pipeline runs.

    Note: this is a connection-rate limit, not a concurrency cap.  Zombie
    streams are bounded by the 300 s server-side timeout in the generator.

    Key prefix: ``sse:`` — does not collide with chat or create keys.

    Raises:
        fastapi.HTTPException: 429 with ``Retry-After`` header when the limit
            is exceeded.
    """
    from fastapi import HTTPException

    from app.core.config import settings as _settings

    per_min_limit = _settings.mini_sse_ip_per_min_limit
    key = f"sse:{ip}"
    limiter = store or get_default_rate_limit_store()

    try:
        decision = await limiter.hit(key, per_min_limit, 60)
    except Exception as exc:
        logger.exception("mini_sse_throttle persistent store unavailable")
        raise _storage_unavailable_exception() from exc
    if not decision.allowed:
        retry_after = decision.retry_after or 60
        logger.warning(
            "mini_sse_throttle exceeded ip=%s limit=%d/min",
            ip,
            per_min_limit,
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"SSE connection rate limit exceeded: {per_min_limit} connections per minute. "
                f"Please wait {retry_after}s before retrying."
            ),
            headers={"Retry-After": str(retry_after)},
        )


class IPRateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter based on IP, user, or auth endpoint."""

    def __init__(
        self,
        app,
        *,
        store: SlidingRateLimitStore | None = None,
    ):
        super().__init__(app)
        self._store = store or get_default_rate_limit_store()

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip non-API and health paths
        if path in _SKIP_PATHS or not path.startswith("/api"):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"

        # 1. Auth endpoint rate limit (strictest)
        try:
            if path in _AUTH_PATHS:
                key = f"auth:{ip}"
                max_req, window = AUTH_ENDPOINT_LIMIT
                decision = await self._store.hit(key, max_req, window)
                if not decision.allowed:
                    logger.warning("Auth rate limit exceeded: ip=%s path=%s", ip, path)
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": (
                                "Too many authentication attempts. "
                                f"Limit: {max_req} per {window}s."
                            )
                        },
                    )

            # 2. Check for authenticated user (via Authorization header presence)
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                # Authenticated: rate limit by a hash of the token to avoid storing raw tokens
                # Use a truncated token as key (first 16 chars of the bearer value)
                token_prefix = auth_header[7:23]
                key = f"user:{token_prefix}"
                max_req, window = AUTH_LIMIT
            else:
                # Unauthenticated: rate limit by IP
                key = f"ip:{ip}"
                max_req, window = UNAUTH_LIMIT

            decision = await self._store.hit(key, max_req, window)
        except Exception:
            # Fail open: log the outage but let the request through.
            # Returning 503 here means *every* request is blocked when the rate-limit
            # store (Neon DB) has a transient hiccup — including unauthenticated reads
            # like GET /api/minis that the landing page depends on (MINI-258).
            logger.exception(
                "Persistent rate limit store unavailable; failing open for path=%s",
                path,
            )
            return await call_next(request)

        if not decision.allowed:
            logger.warning("Rate limit exceeded: key=%s path=%s", key.split(":")[0], path)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Limit: {max_req} requests per {window}s."
                },
            )

        return await call_next(request)
