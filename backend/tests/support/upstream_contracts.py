"""Recorded upstream HTTP contract fixtures for integration tests.

The harness is intentionally test-only. It records and replays provider-shaped
HTTP responses at the ``httpx`` transport boundary so tests can cover GitHub or
LLM API contracts without depending on live upstream availability by default.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import pytest


class UpstreamFixtureMode(StrEnum):
    """Execution mode for a recorded upstream fixture."""

    REPLAY = "replay"
    RECORD = "record"
    LIVE = "live"


class UpstreamFixtureError(AssertionError):
    """Raised when replay cannot satisfy a request or recorded data is unsafe."""


SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
    "openai-api-key",
}
SENSITIVE_FIELD_NAMES = {
    "access_token",
    "api_key",
    "authorization",
    "client_secret",
    "github_token",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
}
REDACTED = "<REDACTED>"


@dataclass(frozen=True)
class UpstreamFixtureConfig:
    """Configuration for a single upstream fixture file."""

    path: Path
    mode: UpstreamFixtureMode = UpstreamFixtureMode.REPLAY
    provider: str = "github"
    required_env: Sequence[str] = ()
    live_gate_env: str = "UPSTREAM_CONTRACT_LIVE"


def mode_from_env(env_var: str = "UPSTREAM_CONTRACT_MODE") -> UpstreamFixtureMode:
    """Read fixture mode from the environment, defaulting to deterministic replay."""

    raw = os.getenv(env_var, UpstreamFixtureMode.REPLAY.value).strip().lower()
    try:
        return UpstreamFixtureMode(raw)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in UpstreamFixtureMode)
        raise UpstreamFixtureError(f"{env_var} must be one of: {allowed}") from exc


def require_live_upstream(config: UpstreamFixtureConfig) -> None:
    """Skip unless live upstream recording is explicitly enabled and configured."""

    if os.getenv(config.live_gate_env) != "1":
        pytest.skip(f"live upstream fixtures require {config.live_gate_env}=1")

    missing = [name for name in config.required_env if not os.getenv(name)]
    if missing:
        pytest.skip("live upstream fixtures missing required env: " + ", ".join(missing))


class UpstreamFixtureTransport(httpx.AsyncBaseTransport):
    """``httpx`` transport that replays or records upstream interactions."""

    def __init__(self, config: UpstreamFixtureConfig):
        self.config = config
        self._interactions: list[dict[str, Any]] = []
        self._cursor = 0
        self._record_transport: httpx.AsyncHTTPTransport | None = None

        if config.mode == UpstreamFixtureMode.REPLAY:
            self._interactions = _load_fixture(config.path)
        else:
            require_live_upstream(config)
            self._record_transport = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.config.mode == UpstreamFixtureMode.REPLAY:
            return await self._replay(request)

        if self._record_transport is None:  # pragma: no cover
            raise UpstreamFixtureError("record transport was not initialized")

        response = await self._record_transport.handle_async_request(request)
        body = await response.aread()
        self._interactions.append(_interaction_from_exchange(request, response, body))

        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=body,
            extensions=response.extensions,
            request=request,
        )

    async def _replay(self, request: httpx.Request) -> httpx.Response:
        if self._cursor >= len(self._interactions):
            raise UpstreamFixtureError(f"unexpected upstream request: {_request_key(request)}")

        interaction = self._interactions[self._cursor]
        expected = interaction["request"]
        actual_key = _request_key(request)
        expected_key = _request_key_from_parts(expected["method"], expected["url"])
        if actual_key != expected_key:
            raise UpstreamFixtureError(
                f"upstream request mismatch at index {self._cursor}: "
                f"expected {expected_key}, got {actual_key}"
            )

        expected_body = expected.get("body")
        actual_body = _json_or_text(request.content)
        if expected_body != actual_body:
            raise UpstreamFixtureError(
                f"upstream request body mismatch at index {self._cursor}: "
                f"expected {expected_body!r}, got {actual_body!r}"
            )

        self._cursor += 1
        recorded_response = interaction["response"]
        return httpx.Response(
            status_code=recorded_response["status_code"],
            headers=recorded_response.get("headers") or {},
            content=recorded_response.get("body", ""),
            request=request,
        )

    async def aclose(self) -> None:
        if self._record_transport is not None:
            await self._record_transport.aclose()

        if self.config.mode == UpstreamFixtureMode.RECORD:
            _write_fixture(
                self.config.path,
                {
                    "version": 1,
                    "provider": self.config.provider,
                    "interactions": self._interactions,
                },
            )

    def assert_all_consumed(self) -> None:
        """Assert replay mode consumed every recorded interaction."""

        if self.config.mode != UpstreamFixtureMode.REPLAY:
            return
        if self._cursor != len(self._interactions):
            remaining = len(self._interactions) - self._cursor
            raise UpstreamFixtureError(f"{remaining} recorded upstream interaction(s) unused")


def redact_value(value: Any, *, env_values: Iterable[str] | None = None) -> Any:
    """Recursively redact common secret fields and configured environment values."""

    secret_values = {secret for secret in env_values or _known_secret_values() if secret}
    return _redact_value(value, secret_values=secret_values)


def _redact_value(value: Any, *, secret_values: set[str]) -> Any:
    """Recursive implementation for ``redact_value``."""

    if isinstance(value, Mapping):
        return {
            key: REDACTED
            if str(key).lower() in SENSITIVE_FIELD_NAMES
            else _redact_value(item, secret_values=secret_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, secret_values=secret_values) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in secret_values:
            redacted = redacted.replace(secret, REDACTED)
        return redacted
    return value


def _load_fixture(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise UpstreamFixtureError(f"upstream fixture does not exist: {path}")

    body = json.loads(path.read_text())
    interactions = body.get("interactions")
    if not isinstance(interactions, list):
        raise UpstreamFixtureError(f"upstream fixture missing interactions list: {path}")
    return interactions


def _write_fixture(path: Path, body: dict[str, Any]) -> None:
    redacted = redact_value(body)
    serialized = json.dumps(redacted, indent=2, sort_keys=True) + "\n"
    if _looks_unredacted(serialized):
        raise UpstreamFixtureError(f"refusing to write fixture with probable secret: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized)


def _interaction_from_exchange(
    request: httpx.Request,
    response: httpx.Response,
    body: bytes,
) -> dict[str, Any]:
    return {
        "request": {
            "method": request.method,
            "url": _normalize_url(str(request.url)),
            "headers": _redact_headers(request.headers),
            "body": _json_or_text(request.content),
        },
        "response": {
            "status_code": response.status_code,
            "headers": _redact_headers(response.headers),
            "body": _decode_body(body),
        },
    }


def _redact_headers(headers: httpx.Headers | Mapping[str, str]) -> dict[str, str]:
    return {
        key: REDACTED if key.lower() in SENSITIVE_HEADER_NAMES else redact_value(value)
        for key, value in sorted(headers.items(), key=lambda item: item[0].lower())
    }


def _request_key(request: httpx.Request) -> str:
    return _request_key_from_parts(request.method, str(request.url))


def _request_key_from_parts(method: str, url: str) -> str:
    return f"{method.upper()} {_normalize_url(url)}"


def _normalize_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _json_or_text(body: bytes) -> Any:
    if not body:
        return None
    decoded = _decode_body(body)
    try:
        return json.loads(decoded)
    except json.JSONDecodeError:
        return decoded


def _decode_body(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _known_secret_values() -> set[str]:
    names = {
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GITHUB_TOKEN",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
    }
    return {os.getenv(name, "") for name in names}


def _looks_unredacted(serialized: str) -> bool:
    lower = serialized.lower()
    suspicious_markers = ("bearer ghp_", "bearer github_pat_", "sk-", "xoxb-")
    return any(marker in lower for marker in suspicious_markers)
