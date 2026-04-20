"""GitHub HTTP helper with rate-limit aware retry and exponential backoff.

All GitHub REST calls from ingestion / explorer code should go through
``gh_request`` so that 429, rate-limited 403, and transient 5xx responses are
handled uniformly (Retry-After parsing, X-RateLimit-Reset fallback, exponential
backoff for server errors).

The helper logs a structured ``gh_request retry`` warning on every retry so
operators can grep Fly logs.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)

# Maximum single sleep between retries (seconds). Caps Retry-After / reset-delta
# so we never block an explorer indefinitely.
_MAX_SLEEP_SECONDS = 60.0

# Number of retries attempted on transient failures before giving up.
_MAX_RETRIES = 3


def _parse_retry_sleep(response: httpx.Response) -> float:
    """Extract sleep duration from Retry-After or X-RateLimit-Reset headers.

    Falls back to 1.0s if both are missing / unparseable. Caps at
    ``_MAX_SLEEP_SECONDS``.
    """
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), _MAX_SLEEP_SECONDS)
        except (TypeError, ValueError):
            pass

    reset = response.headers.get("X-RateLimit-Reset")
    if reset:
        try:
            delta = float(reset) - time.time()
            if delta > 0:
                return min(delta, _MAX_SLEEP_SECONDS)
        except (TypeError, ValueError):
            pass

    return 1.0


def _is_rate_limited(response: httpx.Response) -> bool:
    """True when the response indicates a GitHub rate-limit condition."""
    if response.status_code == 429:
        return True
    if response.status_code == 403:
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining == "0":
            return True
    return False


async def gh_request(client: httpx.AsyncClient, method: str, url: str, **kw) -> httpx.Response:
    """Issue a GitHub request with rate-limit aware retry and 5xx backoff.

    On 429 (or 403 with ``X-RateLimit-Remaining: 0``): parse ``Retry-After`` or
    compute ``X-RateLimit-Reset - now``; sleep (capped at 60s); retry up to
    3 times.

    On 5xx: exponential backoff 1s -> 2s -> 4s, up to 3 retries.

    Returns the final ``httpx.Response``. Other 4xx responses are returned
    directly so callers can inspect / handle them. Network-level exceptions are
    retried with exponential backoff; the final exception bubbles up after
    ``_MAX_RETRIES`` attempts.
    """
    last_exc: Exception | None = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.request(method, url, **kw)
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt >= _MAX_RETRIES:
                raise
            sleep_s = min(2**attempt, _MAX_SLEEP_SECONDS)
            logger.warning(
                "gh_request retry",
                extra={
                    "url": url,
                    "status": None,
                    "error": repr(exc),
                    "attempt": attempt + 1,
                    "sleep_s": sleep_s,
                },
            )
            await asyncio.sleep(sleep_s)
            continue

        # Rate-limited (429 or 403 with remaining=0): respect server hints.
        if _is_rate_limited(response):
            if attempt >= _MAX_RETRIES:
                return response
            sleep_s = _parse_retry_sleep(response)
            logger.warning(
                "gh_request retry",
                extra={
                    "url": url,
                    "status": response.status_code,
                    "attempt": attempt + 1,
                    "sleep_s": sleep_s,
                },
            )
            await asyncio.sleep(sleep_s)
            continue

        # Transient server error: exponential backoff.
        if 500 <= response.status_code < 600:
            if attempt >= _MAX_RETRIES:
                return response
            sleep_s = min(2**attempt, _MAX_SLEEP_SECONDS)
            logger.warning(
                "gh_request retry",
                extra={
                    "url": url,
                    "status": response.status_code,
                    "attempt": attempt + 1,
                    "sleep_s": sleep_s,
                },
            )
            await asyncio.sleep(sleep_s)
            continue

        # Success path (2xx) or non-retryable 4xx: return to caller.
        return response

    # Unreachable: the loop always returns or raises. Satisfy the type checker.
    if last_exc is not None:  # pragma: no cover
        raise last_exc
    raise RuntimeError("gh_request exhausted retries without a response")  # pragma: no cover
