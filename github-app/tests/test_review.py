from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.config import settings
from app.review import get_mini


class _AsyncClientStub:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str, *, headers: dict[str, str] | None = None, timeout: float):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return self._response


@pytest.mark.asyncio
async def test_get_mini_uses_trusted_lookup_path_and_header():
    stub = _AsyncClientStub(
        httpx.Response(
            200,
            request=httpx.Request(
                "GET",
                f"{settings.minis_api_url}/api/minis/trusted/by-username/alliecatowo",
            ),
            json={
                "id": "mini-123",
                "username": "alliecatowo",
                "display_name": "Allie",
                "avatar_url": None,
                "status": "ready",
                "system_prompt": "be pragmatic",
            },
        )
    )

    with patch.object(settings, "trusted_service_secret", "secret-for-tests"):
        with patch("app.review.httpx.AsyncClient", return_value=stub):
            mini = await get_mini("alliecatowo")

    assert mini is not None
    assert mini["system_prompt"] == "be pragmatic"
    assert stub.calls == [
        {
            "url": f"{settings.minis_api_url}/api/minis/trusted/by-username/alliecatowo",
            "headers": {"X-Trusted-Service-Secret": "secret-for-tests"},
            "timeout": 10.0,
        }
    ]


@pytest.mark.asyncio
async def test_get_mini_requires_trusted_service_secret_config():
    with patch.object(settings, "trusted_service_secret", ""):
        mini = await get_mini("alliecatowo")

    assert mini is None
