"""Minis MCP server.

Thin FastMCP wrapper around the Minis backend API.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from fastmcp import FastMCP

DEFAULT_BACKEND_URL = "http://localhost:8000"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
DEFAULT_READ_TIMEOUT_SECONDS = 300.0

mcp = FastMCP(
    "minis",
    instructions=(
        "Create minis, inspect their profiles, and chat with them through the Minis backend API."
    ),
)


class BackendError(RuntimeError):
    """Raised when the Minis backend returns an error."""


class MiniNotFoundError(BackendError):
    """Raised when a mini cannot be resolved from an identifier."""


def _backend_url() -> str:
    return os.environ.get("MINIS_BACKEND_URL", DEFAULT_BACKEND_URL).rstrip("/")


def _auth_token() -> str:
    return os.environ.get("MINIS_AUTH_TOKEN", "").strip()


def _api(path: str) -> str:
    return f"{_backend_url()}/api{path}"


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _make_client(*, timeout: httpx.Timeout) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True)


def _auth_headers(require_auth: bool) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = _auth_token()
    if require_auth and not token:
        raise BackendError(
            "MINIS_AUTH_TOKEN is required for this tool because the backend route is authenticated."
        )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _request_json(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 120.0,
    require_auth: bool = False,
) -> Any:
    try:
        async with _make_client(
            timeout=httpx.Timeout(timeout, connect=DEFAULT_CONNECT_TIMEOUT_SECONDS)
        ) as client:
            response = await client.request(
                method,
                _api(path),
                json=json_body,
                headers=_auth_headers(require_auth),
            )
    except httpx.ConnectError as exc:
        raise BackendError(f"Cannot connect to Minis backend at {_backend_url()}") from exc

    if response.status_code >= 400:
        detail: Any = response.text
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail", detail)
        raise BackendError(f"{response.status_code} {detail}")

    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        return response.json()
    return response.text


async def _resolve_mini_id(identifier: str) -> str:
    if _is_uuid(identifier):
        return identifier

    mini = await _request_json("GET", f"/minis/by-username/{quote(identifier, safe='')}")
    if not isinstance(mini, dict) or not mini.get("id"):
        raise MiniNotFoundError(f"Mini '{identifier}' could not be resolved to an id.")
    return str(mini["id"])


async def _fetch_mini(identifier: str) -> dict[str, Any]:
    if _is_uuid(identifier):
        path = f"/minis/{identifier}"
    else:
        path = f"/minis/by-username/{quote(identifier, safe='')}"

    mini = await _request_json("GET", path)
    if not isinstance(mini, dict):
        raise BackendError("Expected a mini object from the backend.")
    return mini


async def _stream_sse_events(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
    require_auth: bool = False,
) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    event_type = "message"
    data_lines: list[str] = []

    try:
        async with _make_client(
            timeout=httpx.Timeout(
                connect=DEFAULT_CONNECT_TIMEOUT_SECONDS,
                read=timeout_seconds,
                write=DEFAULT_CONNECT_TIMEOUT_SECONDS,
                pool=DEFAULT_CONNECT_TIMEOUT_SECONDS,
            )
        ) as client:
            async with client.stream(
                method,
                _api(path),
                json=json_body,
                headers={**_auth_headers(require_auth), "Accept": "text/event-stream"},
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    detail = body.decode()
                    try:
                        payload = json.loads(detail)
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict):
                        detail = payload.get("detail", detail)
                    raise BackendError(f"{response.status_code} {detail}")

                async for line in response.aiter_lines():
                    if line == "":
                        if data_lines:
                            events.append((event_type, "\n".join(data_lines)))
                        event_type = "message"
                        data_lines = []
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_type = line.removeprefix("event:").strip() or "message"
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line.removeprefix("data:").lstrip())

                if data_lines:
                    events.append((event_type, "\n".join(data_lines)))
    except httpx.ConnectError as exc:
        raise BackendError(f"Cannot connect to Minis backend at {_backend_url()}") from exc
    except httpx.ReadTimeout as exc:
        raise BackendError(f"SSE request timed out after {timeout_seconds} seconds.") from exc

    return events


@mcp.tool()
async def list_sources() -> list[dict[str, Any]]:
    """List the ingestion sources that the backend currently exposes for mini creation."""

    sources = await _request_json("GET", "/minis/sources")
    if not isinstance(sources, list):
        raise BackendError("Expected a source list from the backend.")
    return sources


@mcp.tool()
async def create_mini(
    username: str,
    sources: list[str] | None = None,
    excluded_repos: list[str] | None = None,
    source_identifiers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create or regenerate a mini.

    This tool requires `MINIS_AUTH_TOKEN` because the backend route is authenticated.
    """

    result = await _request_json(
        "POST",
        "/minis",
        json_body={
            "username": username,
            "sources": sources or ["github"],
            "excluded_repos": excluded_repos or [],
            "source_identifiers": source_identifiers or {},
        },
        require_auth=True,
    )
    if not isinstance(result, dict):
        raise BackendError("Expected a mini summary object from the backend.")
    return result


@mcp.tool()
async def list_minis(mine: bool = False) -> list[dict[str, Any]]:
    """List public minis, or your own minis when `mine=true` and auth is configured."""

    result = await _request_json(
        "GET",
        f"/minis?mine={'true' if mine else 'false'}",
        require_auth=mine,
    )
    if not isinstance(result, list):
        raise BackendError("Expected a mini list from the backend.")
    return result


@mcp.tool()
async def get_mini(identifier: str) -> dict[str, Any]:
    """Fetch a mini by UUID or username."""

    return await _fetch_mini(identifier)


@mcp.tool()
async def get_mini_status(
    identifier: str,
    timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Read pipeline progress events for a mini until completion or timeout."""

    mini_id = await _resolve_mini_id(identifier)
    events = await _stream_sse_events(
        "GET",
        f"/minis/{mini_id}/status",
        timeout_seconds=timeout_seconds,
    )

    parsed: list[dict[str, Any]] = []
    for event_type, data in events:
        if event_type == "progress":
            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                payload = {"raw": data}
            if isinstance(payload, dict):
                payload["event"] = event_type
                parsed.append(payload)
            else:
                parsed.append({"event": event_type, "data": payload})
            continue
        parsed.append({"event": event_type, "data": data})
        if event_type in {"done", "timeout"}:
            break
    return parsed


@mcp.tool()
async def chat_with_mini(
    identifier: str,
    message: str,
    history: list[dict[str, str]] | None = None,
    conversation_id: str | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Chat with a mini and return the assembled response text.

    Use `conversation_id` from a prior response to continue an authenticated conversation.
    """

    mini_id = await _resolve_mini_id(identifier)
    events = await _stream_sse_events(
        "POST",
        f"/minis/{mini_id}/chat",
        json_body={
            "message": message,
            "history": history or [],
            "conversation_id": conversation_id,
        },
        timeout_seconds=timeout_seconds,
    )

    response_chunks: list[str] = []
    resolved_conversation_id = conversation_id
    for event_type, data in events:
        if event_type == "conversation_id":
            resolved_conversation_id = data
            continue
        if event_type == "chunk":
            response_chunks.append(data)
            continue
        if event_type == "error":
            raise BackendError(data)

    return {
        "mini_id": mini_id,
        "conversation_id": resolved_conversation_id,
        "response": "".join(response_chunks),
    }


@mcp.tool()
async def get_mini_graph(identifier: str) -> dict[str, Any]:
    """Fetch the persisted knowledge graph and principles data for a mini."""

    mini_id = await _resolve_mini_id(identifier)
    result = await _request_json("GET", f"/minis/{mini_id}/graph")
    if not isinstance(result, dict):
        raise BackendError("Expected a graph payload from the backend.")
    return result


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
