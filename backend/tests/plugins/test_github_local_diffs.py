"""Unit tests for local-clone-first commit diff fetching (Wave 3A)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ingestion.github import fetch_commit_diffs


MINI_ID = "00000000-0000-0000-0000-000000000001"
OWNER = "torvalds"
REPO = "linux"
REPO_FULL = f"{OWNER}/{REPO}"
SHA = "deadbeefdeadbeef"

_COMMITS = [
    {
        "sha": SHA,
        "repository": {"full_name": REPO_FULL},
        "commit": {
            "message": "fix: something",
            "author": {"name": "Linus", "date": "2026-01-01T00:00:00Z"},
        },
        "author": {"login": OWNER},
        "html_url": f"https://github.com/{REPO_FULL}/commit/{SHA}",
    }
]

_FAKE_DIFF = "diff --git a/foo.c b/foo.c\n--- a/foo.c\n+++ b/foo.c\n@@ -1 +1 @@\n-old\n+new"


@pytest.mark.asyncio
async def test_local_diff_used_when_available():
    """When local diff succeeds, REST is NOT called for that commit."""
    mock_client = MagicMock()
    mock_clone_root = Path("/fake/clone")

    with (
        patch(
            "app.explorer.clone_manager.ensure_clone",
            new=AsyncMock(return_value=mock_clone_root),
        ),
        patch(
            "app.explorer.repo_tools.open_diff",
            new=AsyncMock(return_value=_FAKE_DIFF),
        ),
        patch("app.ingestion.github._get", new=AsyncMock()) as mock_get,
    ):
        diffs = await fetch_commit_diffs(
            mock_client,
            _COMMITS,
            mini_id=MINI_ID,
            prefer_local_diffs=True,
        )

    assert len(diffs) == 1
    assert diffs[0]["_source"] == "local_clone"
    assert diffs[0]["sha"] == SHA
    assert _FAKE_DIFF in diffs[0]["files"][0]["patch"]
    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_rest_fallback_when_local_diff_raises():
    """When local clone fetch raises, REST is called as fallback."""
    mock_client = MagicMock()
    rest_detail = {
        "sha": SHA,
        "repo": REPO_FULL,
        "commit": {"message": "fix: something"},
        "files": [{"filename": "foo.c", "patch": "rest patch"}],
        "stats": {},
    }

    with (
        patch(
            "app.explorer.clone_manager.ensure_clone",
            new=AsyncMock(side_effect=RuntimeError("clone failed")),
        ),
        patch("app.ingestion.github._get", new=AsyncMock(return_value=rest_detail)) as mock_get,
    ):
        diffs = await fetch_commit_diffs(
            mock_client,
            _COMMITS,
            mini_id=MINI_ID,
            prefer_local_diffs=True,
        )

    assert len(diffs) == 1
    assert diffs[0].get("_source") != "local_clone"
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_rest_fallback_when_open_diff_returns_sentinel():
    """When open_diff returns a sentinel string, REST is called as fallback."""
    mock_client = MagicMock()
    mock_clone_root = Path("/fake/clone")
    rest_detail = {
        "sha": SHA,
        "repo": REPO_FULL,
        "commit": {"message": "fix: something"},
        "files": [],
        "stats": {},
    }

    with (
        patch(
            "app.explorer.clone_manager.ensure_clone",
            new=AsyncMock(return_value=mock_clone_root),
        ),
        patch(
            "app.explorer.repo_tools.open_diff",
            new=AsyncMock(return_value="<git show error (rc=128): bad sha>"),
        ),
        patch("app.ingestion.github._get", new=AsyncMock(return_value=rest_detail)) as mock_get,
    ):
        diffs = await fetch_commit_diffs(
            mock_client,
            _COMMITS,
            mini_id=MINI_ID,
            prefer_local_diffs=True,
        )

    assert len(diffs) == 1
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_prefer_local_false_skips_clone():
    """When prefer_local_diffs=False, clone is never attempted and REST is used."""
    mock_client = MagicMock()
    rest_detail = {
        "sha": SHA,
        "repo": REPO_FULL,
        "commit": {"message": "fix: something"},
        "files": [],
        "stats": {},
    }

    with (
        patch(
            "app.explorer.clone_manager.ensure_clone",
            new=AsyncMock(),
        ) as mock_ensure,
        patch("app.ingestion.github._get", new=AsyncMock(return_value=rest_detail)) as mock_get,
    ):
        diffs = await fetch_commit_diffs(
            mock_client,
            _COMMITS,
            mini_id=MINI_ID,
            prefer_local_diffs=False,
        )

    assert len(diffs) == 1
    mock_ensure.assert_not_called()
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_no_mini_id_falls_back_to_rest():
    """Without mini_id, local clone is not attempted even if prefer_local_diffs=True."""
    mock_client = MagicMock()
    rest_detail = {
        "sha": SHA,
        "repo": REPO_FULL,
        "commit": {"message": "fix: something"},
        "files": [],
        "stats": {},
    }

    with (
        patch(
            "app.explorer.clone_manager.ensure_clone",
            new=AsyncMock(),
        ) as mock_ensure,
        patch("app.ingestion.github._get", new=AsyncMock(return_value=rest_detail)) as mock_get,
    ):
        diffs = await fetch_commit_diffs(
            mock_client,
            _COMMITS,
            mini_id=None,
            prefer_local_diffs=True,
        )

    assert len(diffs) == 1
    mock_ensure.assert_not_called()
    mock_get.assert_called_once()
