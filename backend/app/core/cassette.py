"""Deterministic cassette/replay storage for LLM request/response payloads."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

_CASSETTE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "cassettes"


class CassetteMissError(FileNotFoundError):
    """Raised when replay mode cannot find a cassette for a request hash."""


def get_cassette_mode() -> str:
    """Return cassette mode: 'record', 'replay', or empty string for pass-through."""
    return (os.environ.get("MINIS_CASSETTE_MODE") or "").strip().lower()


def _get_run_id() -> str:
    return (os.environ.get("MINIS_CASSETTE_RUN_ID") or "default").strip() or "default"


def _request_hash(request_dict: dict[str, Any]) -> str:
    canonical = json.dumps(request_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_response(request_dict: dict[str, Any], response_dict: dict[str, Any]) -> None:
    """Persist response JSON for request hash when cassette mode is 'record'."""
    if get_cassette_mode() != "record":
        return

    request_hash = _request_hash(request_dict)
    run_dir = _CASSETTE_ROOT / _get_run_id()
    run_dir.mkdir(parents=True, exist_ok=True)
    cassette_path = run_dir / f"{request_hash}.json"

    payload = {
        "request_hash": request_hash,
        "response": response_dict,
    }
    cassette_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")


def replay_response(request_dict: dict[str, Any]) -> dict[str, Any]:
    """Load stored response JSON for a request hash or raise CassetteMissError."""
    request_hash = _request_hash(request_dict)
    cassette_path = _CASSETTE_ROOT / _get_run_id() / f"{request_hash}.json"

    if not cassette_path.exists():
        raise CassetteMissError(
            "Cassette replay miss for request hash "
            f"{request_hash}. Expected fixture at {cassette_path}. "
            "Record it with MINIS_CASSETTE_MODE=record."
        )

    payload = json.loads(cassette_path.read_text(encoding="utf-8"))
    response = payload.get("response")
    if not isinstance(response, dict):
        raise CassetteMissError(
            f"Invalid cassette format at {cassette_path}: missing object 'response' for hash {request_hash}."
        )
    return response
