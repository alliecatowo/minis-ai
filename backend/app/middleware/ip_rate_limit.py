"""IP-based sliding window rate limiting middleware.

Uses an in-memory dict with TTL cleanup -- no Redis needed.
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
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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

# Paths to skip (health checks, static assets)
_SKIP_PATHS = frozenset({"/api/health", "/docs", "/redoc", "/openapi.json"})

# ── Sliding window storage ───────────────────────────────────────────────────

# key -> list of request timestamps
_windows: dict[str, list[float]] = defaultdict(list)

# Track last cleanup time to avoid cleaning on every request
_last_cleanup = 0.0
_CLEANUP_INTERVAL = 30.0  # Run cleanup every 30 seconds

# Default largest window for non-chat keys (seconds)
_MAX_WINDOW = 60
# Hourly window for chat/create throttle keys
_HOURLY_MAX_WINDOW = 3600


def _window_for_key(key: str) -> int:
    """Return the retention window (seconds) for a given key.

    Chat keys (prefix ``chat:``) and create keys (prefix ``create:``) use a
    3600 s hourly window; all others use the standard 60 s window.
    """
    if key.startswith(("chat:", "create:")):
        return _HOURLY_MAX_WINDOW
    return _MAX_WINDOW


def _cleanup_expired() -> None:
    """Remove expired entries from the sliding window dict."""
    global _last_cleanup
    now = time.monotonic()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return
    _last_cleanup = now

    keys_to_delete: list[str] = []
    for key, timestamps in _windows.items():
        cutoff = now - _window_for_key(key)
        timestamps[:] = [t for t in timestamps if t > cutoff]
        if not timestamps:
            keys_to_delete.append(key)
    for key in keys_to_delete:
        del _windows[key]


def _check_limit(key: str, max_requests: int, window_seconds: int) -> bool:
    """Check if a key is within its rate limit. Returns True if allowed."""
    now = time.monotonic()
    cutoff = now - window_seconds
    timestamps = _windows[key]

    # Prune expired entries
    timestamps[:] = [t for t in timestamps if t > cutoff]

    if len(timestamps) >= max_requests:
        return False

    timestamps.append(now)
    return True


def _oldest_in_window(key: str, window_seconds: int) -> float:
    """Return the oldest timestamp in the window, or ``now`` if window is empty."""
    now = time.monotonic()
    cutoff = now - window_seconds
    timestamps = [t for t in _windows.get(key, []) if t > cutoff]
    return min(timestamps) if timestamps else now


# ── Per-IP + per-mini chat throttle (ALLIE-405) ─────────────────────────────


def check_chat_ip_mini_limit(ip: str, mini_id: str, user: object | None = None) -> None:
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

    base_key = f"chat:{ip}:{mini_id}"
    burst_key = f"{base_key}:burst"
    hourly_key = f"{base_key}:hourly"

    # Check burst first (stricter, smaller window)
    if not _check_limit(burst_key, burst_limit, 60):
        oldest = _oldest_in_window(burst_key, 60)
        retry_after = max(1, int(60 - (time.monotonic() - oldest)))
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
    if not _check_limit(hourly_key, hourly_limit, 3600):
        oldest = _oldest_in_window(hourly_key, 3600)
        retry_after = max(1, int(3600 - (time.monotonic() - oldest)))
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


def check_mini_create_ip_limit(ip: str, user: object | None = None) -> None:
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

    if not _check_limit(key, hourly_limit, 3600):
        oldest = _oldest_in_window(key, 3600)
        retry_after = max(1, int(3600 - (time.monotonic() - oldest)))
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


def check_mini_sse_ip_limit(ip: str) -> None:
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

    if not _check_limit(key, per_min_limit, 60):
        oldest = _oldest_in_window(key, 60)
        retry_after = max(1, int(60 - (time.monotonic() - oldest)))
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

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip non-API and health paths
        if path in _SKIP_PATHS or not path.startswith("/api"):
            return await call_next(request)

        # Periodic cleanup
        _cleanup_expired()

        ip = request.client.host if request.client else "unknown"

        # 1. Auth endpoint rate limit (strictest)
        if path in _AUTH_PATHS:
            key = f"auth:{ip}"
            max_req, window = AUTH_ENDPOINT_LIMIT
            if not _check_limit(key, max_req, window):
                logger.warning("Auth rate limit exceeded: ip=%s path=%s", ip, path)
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Too many authentication attempts. Limit: {max_req} per {window}s."
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

        if not _check_limit(key, max_req, window):
            logger.warning("Rate limit exceeded: key=%s path=%s", key.split(":")[0], path)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": f"Rate limit exceeded. Limit: {max_req} requests per {window}s."
                },
            )

        return await call_next(request)
