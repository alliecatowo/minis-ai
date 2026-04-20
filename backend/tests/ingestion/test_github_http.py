"""Unit tests for ``app.ingestion.github_http.gh_request``."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.ingestion.github_http import gh_request


def _make_response(
    status_code: int,
    headers: dict[str, str] | None = None,
    json_body: dict | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers=headers or {},
        json=json_body if json_body is not None else {},
        request=httpx.Request("GET", "https://api.github.com/users/x"),
    )


@pytest.mark.asyncio
async def test_gh_request_returns_200_immediately():
    """A 2xx response should be returned on the first attempt with no sleeping."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(return_value=_make_response(200, json_body={"ok": True}))

    with patch("app.ingestion.github_http.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        resp = await gh_request(client, "GET", "https://api.github.com/users/x")

    assert resp.status_code == 200
    assert client.request.await_count == 1
    assert sleep_mock.await_count == 0


@pytest.mark.asyncio
async def test_gh_request_retries_on_429_with_retry_after():
    """429 with Retry-After should be retried; sleep honored up to cap."""
    client = AsyncMock(spec=httpx.AsyncClient)
    rate_limited = _make_response(429, headers={"Retry-After": "2"})
    success = _make_response(200, json_body={"ok": True})
    client.request = AsyncMock(side_effect=[rate_limited, success])

    with patch("app.ingestion.github_http.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        resp = await gh_request(client, "GET", "https://api.github.com/users/x")

    assert resp.status_code == 200
    assert client.request.await_count == 2
    assert sleep_mock.await_count == 1
    # Retry-After honored: sleep(2.0)
    sleep_mock.assert_awaited_with(2.0)


@pytest.mark.asyncio
async def test_gh_request_retries_on_403_rate_limited():
    """403 with X-RateLimit-Remaining: 0 should be retried (rate-limit condition)."""
    client = AsyncMock(spec=httpx.AsyncClient)
    rate_limited = _make_response(
        403,
        headers={"X-RateLimit-Remaining": "0", "Retry-After": "1"},
    )
    success = _make_response(200, json_body={"ok": True})
    client.request = AsyncMock(side_effect=[rate_limited, success])

    with patch("app.ingestion.github_http.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        resp = await gh_request(client, "GET", "https://api.github.com/users/x")

    assert resp.status_code == 200
    assert client.request.await_count == 2
    assert sleep_mock.await_count == 1


@pytest.mark.asyncio
async def test_gh_request_403_without_rate_limit_header_returned_as_is():
    """403 without X-RateLimit-Remaining: 0 is not retried — a real 403."""
    client = AsyncMock(spec=httpx.AsyncClient)
    forbidden = _make_response(403, headers={})
    client.request = AsyncMock(return_value=forbidden)

    with patch("app.ingestion.github_http.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        resp = await gh_request(client, "GET", "https://api.github.com/users/x")

    assert resp.status_code == 403
    assert client.request.await_count == 1
    assert sleep_mock.await_count == 0


@pytest.mark.asyncio
async def test_gh_request_exhausts_retries_on_repeated_500():
    """Three 500 responses should exhaust retries and return the last 500."""
    client = AsyncMock(spec=httpx.AsyncClient)
    server_error = _make_response(500)
    # gh_request attempts up to _MAX_RETRIES + 1 = 4 times. Provide 4 errors.
    client.request = AsyncMock(return_value=server_error)

    with patch("app.ingestion.github_http.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        resp = await gh_request(client, "GET", "https://api.github.com/users/x")

    assert resp.status_code == 500
    # 4 attempts total (initial + 3 retries)
    assert client.request.await_count == 4
    # 3 sleeps between the 4 attempts
    assert sleep_mock.await_count == 3


@pytest.mark.asyncio
async def test_gh_request_retries_5xx_then_succeeds():
    """Two 503s followed by a 200 should return 200 after exponential backoff."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(
        side_effect=[
            _make_response(503),
            _make_response(502),
            _make_response(200, json_body={"ok": True}),
        ]
    )

    with patch("app.ingestion.github_http.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        resp = await gh_request(client, "GET", "https://api.github.com/users/x")

    assert resp.status_code == 200
    assert client.request.await_count == 3
    # Backoff schedule: 2**0 = 1, 2**1 = 2
    assert sleep_mock.await_count == 2


@pytest.mark.asyncio
async def test_gh_request_parses_x_ratelimit_reset_when_no_retry_after():
    """When Retry-After is absent, fall back to X-RateLimit-Reset delta."""
    client = AsyncMock(spec=httpx.AsyncClient)

    # Compute a reset ~5 seconds in the future
    with patch("app.ingestion.github_http.time.time", return_value=1_000_000.0):
        rate_limited = _make_response(
            429,
            headers={"X-RateLimit-Reset": "1000005"},
        )
        success = _make_response(200)
        client.request = AsyncMock(side_effect=[rate_limited, success])

        with patch("app.ingestion.github_http.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            resp = await gh_request(client, "GET", "https://api.github.com/users/x")

    assert resp.status_code == 200
    assert sleep_mock.await_count == 1
    # Reset-delta is 5.0 seconds
    sleep_mock.assert_awaited_with(5.0)


@pytest.mark.asyncio
async def test_gh_request_caps_sleep_at_60s():
    """Absurdly large Retry-After should be capped at 60s."""
    client = AsyncMock(spec=httpx.AsyncClient)
    rate_limited = _make_response(429, headers={"Retry-After": "3600"})
    success = _make_response(200)
    client.request = AsyncMock(side_effect=[rate_limited, success])

    with patch("app.ingestion.github_http.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        await gh_request(client, "GET", "https://api.github.com/users/x")

    sleep_mock.assert_awaited_with(60.0)
