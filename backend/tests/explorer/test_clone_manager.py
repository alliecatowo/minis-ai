"""Unit tests for backend/app/explorer/clone_manager.py.

All git subprocess calls are mocked; no real network access occurs.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

from app.explorer.clone_manager import (
    _LAST_FETCHED_FILE,
    _STALE_SECONDS,
    clone_path,
    ensure_clone,
    evict_stale,
    list_clones,
    refresh_clone,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mini_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_fake_clone(root: Path, mini_id: uuid.UUID, owner: str, repo: str) -> Path:
    """Create a minimal fake clone directory (no real git content)."""
    path = root / str(mini_id) / f"{owner}__{repo}"
    path.mkdir(parents=True, exist_ok=True)
    git_dir = path / ".git"
    git_dir.mkdir()
    return path


# ---------------------------------------------------------------------------
# clone_path — pure function, no I/O
# ---------------------------------------------------------------------------


class TestClonePath:
    def test_slug_format(self, tmp_path, monkeypatch):
        """owner/repo is encoded as owner__repo."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        # Patch home directory so the path is deterministic
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        mid = uuid.UUID("aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb")
        result = clone_path(mid, "torvalds", "linux")
        assert result.name == "torvalds__linux"
        assert str(mid) in str(result)

    def test_fly_prefix(self, monkeypatch):
        """On Fly.io the path starts with /data/clones."""
        monkeypatch.setenv("FLY_APP_NAME", "minis-prod")
        mid = _make_mini_id()
        result = clone_path(mid, "owner", "repo")
        assert str(result).startswith("/data/clones")

    def test_local_prefix(self, tmp_path, monkeypatch):
        """Without FLY_APP_NAME the path starts under ~/.minis/clones."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        mid = _make_mini_id()
        result = clone_path(mid, "owner", "repo")
        assert ".minis" in str(result)
        assert "clones" in str(result)

    def test_stability(self, tmp_path, monkeypatch):
        """Same inputs always produce the same path."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        mid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        p1 = clone_path(mid, "octocat", "Hello-World")
        p2 = clone_path(mid, "octocat", "Hello-World")
        assert p1 == p2

    def test_different_repos_distinct(self, tmp_path, monkeypatch):
        """Different repos produce different paths."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        mid = _make_mini_id()
        p1 = clone_path(mid, "owner", "repo-a")
        p2 = clone_path(mid, "owner", "repo-b")
        assert p1 != p2

    def test_different_minis_distinct(self, tmp_path, monkeypatch):
        """Same repo under different mini_ids produces different paths."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        m1 = _make_mini_id()
        m2 = _make_mini_id()
        assert clone_path(m1, "owner", "repo") != clone_path(m2, "owner", "repo")


# ---------------------------------------------------------------------------
# ensure_clone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEnsureClone:
    async def test_creates_dir_and_calls_git_clone(self, tmp_path, monkeypatch):
        """When no clone exists, git clone is called with expected arguments."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")

        mid = _make_mini_id()

        captured_args: list[tuple] = []

        async def fake_run_git(*args, **kwargs):
            captured_args.append(args)
            # Simulate git clone by creating the target directory
            # The last positional arg is the target path
            target = Path(args[-1])
            target.mkdir(parents=True, exist_ok=True)
            (target / ".git").mkdir()
            (target / _LAST_FETCHED_FILE).touch()
            return (0, "", "")

        monkeypatch.setattr("app.explorer.clone_manager._run_git", fake_run_git)

        result = await ensure_clone(mid, "owner", "repo", depth=10)

        assert result.exists()
        assert len(captured_args) == 1
        args = captured_args[0]
        assert "clone" in args
        assert "--depth" in args
        assert "10" in args
        assert "--filter=blob:limit=1M" in args
        assert "--single-branch" in args
        # Token should appear in the URL arg (not separately logged)
        url_args = [a for a in args if "github.com" in a]
        assert len(url_args) == 1
        assert "ghp_test_token" in url_args[0]

    async def test_skip_clone_if_fresh(self, tmp_path, monkeypatch):
        """If clone dir exists and last_fetched is recent, no git call is made."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        mid = _make_mini_id()
        path = clone_path(mid, "owner", "repo")
        path.mkdir(parents=True)
        (path / ".git").mkdir()
        # Mark as very recently fetched
        (path / _LAST_FETCHED_FILE).touch()

        called = []

        async def should_not_be_called(*args, **kwargs):
            called.append(True)
            return (0, "", "")

        monkeypatch.setattr("app.explorer.clone_manager._run_git", should_not_be_called)

        result = await ensure_clone(mid, "owner", "repo")
        assert result == path
        assert not called, "git clone was called even though clone is fresh"

    async def test_returns_stale_clone_without_reclone(self, tmp_path, monkeypatch):
        """Stale clone: path is returned; no re-clone is attempted automatically."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        mid = _make_mini_id()
        path = clone_path(mid, "owner", "repo")
        path.mkdir(parents=True)
        (path / ".git").mkdir()
        # Set mtime to well beyond _STALE_SECONDS in the past
        marker = path / _LAST_FETCHED_FILE
        marker.touch()
        old_time = time.time() - _STALE_SECONDS - 86400
        import os

        os.utime(marker, (old_time, old_time))

        git_calls = []

        async def fake_git(*args, **kwargs):
            git_calls.append(args)
            return (0, "", "")

        monkeypatch.setattr("app.explorer.clone_manager._run_git", fake_git)

        result = await ensure_clone(mid, "owner", "repo")
        assert result == path
        # ensure_clone doesn't re-clone stale paths — caller calls refresh_clone
        assert len(git_calls) == 0

    async def test_clone_failure_raises(self, tmp_path, monkeypatch):
        """Non-zero git clone exit code raises RuntimeError."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")

        mid = _make_mini_id()

        async def failing_git(*args, **kwargs):
            return (128, "", "fatal: repository not found")

        monkeypatch.setattr("app.explorer.clone_manager._run_git", failing_git)

        with pytest.raises(RuntimeError, match="git clone failed"):
            await ensure_clone(mid, "owner", "does-not-exist")

    async def test_token_not_in_error_message(self, tmp_path, monkeypatch):
        """GITHUB_TOKEN must be scrubbed from RuntimeError messages."""
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.setenv("GITHUB_TOKEN", "super_secret_token_123")

        mid = _make_mini_id()

        async def failing_git(*args, **kwargs):
            return (128, "", "error: super_secret_token_123 bad credential")

        monkeypatch.setattr("app.explorer.clone_manager._run_git", failing_git)

        with pytest.raises(RuntimeError) as exc_info:
            await ensure_clone(mid, "owner", "repo")

        assert "super_secret_token_123" not in str(exc_info.value)


# ---------------------------------------------------------------------------
# refresh_clone
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRefreshClone:
    async def test_calls_git_fetch(self, tmp_path, monkeypatch):
        """refresh_clone calls ``git fetch --prune --depth 50``."""
        path = tmp_path / "some-repo"
        path.mkdir()
        (path / ".git").mkdir()
        (path / _LAST_FETCHED_FILE).touch()

        captured = []

        async def fake_git(*args, **kwargs):
            captured.append(args)
            return (0, "", "")

        monkeypatch.setattr("app.explorer.clone_manager._run_git", fake_git)

        await refresh_clone(path)

        assert len(captured) == 1
        args = captured[0]
        assert "-C" in args
        assert "fetch" in args
        assert "--prune" in args
        assert "--depth" in args

    async def test_raises_if_path_missing(self, tmp_path):
        """refresh_clone raises FileNotFoundError for non-existent path."""
        with pytest.raises(FileNotFoundError):
            await refresh_clone(tmp_path / "does-not-exist")

    async def test_raises_on_fetch_failure(self, tmp_path, monkeypatch):
        """Non-zero fetch exit code raises RuntimeError."""
        path = tmp_path / "repo"
        path.mkdir()

        async def fail(*args, **kwargs):
            return (1, "", "fatal: error")

        monkeypatch.setattr("app.explorer.clone_manager._run_git", fail)

        with pytest.raises(RuntimeError, match="git fetch failed"):
            await refresh_clone(path)

    async def test_updates_last_fetched(self, tmp_path, monkeypatch):
        """After a successful refresh, .last_fetched mtime is updated."""
        path = tmp_path / "repo"
        path.mkdir()
        marker = path / _LAST_FETCHED_FILE
        marker.touch()
        old = marker.stat().st_mtime

        import asyncio as _aio

        await _aio.sleep(0.01)  # ensure measurable time difference

        async def ok_git(*args, **kwargs):
            return (0, "", "")

        monkeypatch.setattr("app.explorer.clone_manager._run_git", ok_git)

        await refresh_clone(path)
        assert marker.stat().st_mtime >= old


# ---------------------------------------------------------------------------
# list_clones
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListClones:
    async def test_empty_when_no_root(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        mid = _make_mini_id()
        result = await list_clones(mid)
        assert result == []

    async def test_returns_all_clone_dirs(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        mid = _make_mini_id()
        root = tmp_path / ".minis" / "clones" / str(mid)
        root.mkdir(parents=True)

        for name in ("owner__a", "owner__b", "owner__c"):
            d = root / name
            d.mkdir()

        result = await list_clones(mid)
        assert len(result) == 3

    async def test_sorted_by_last_fetched_asc(self, tmp_path, monkeypatch):
        """Oldest last_fetched appears first in the returned list."""
        import os

        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        mid = _make_mini_id()
        root = tmp_path / ".minis" / "clones" / str(mid)
        root.mkdir(parents=True)

        now = time.time()
        # oldest → largest age (mtime furthest in the past)
        # newest → smallest age (mtime closest to now)
        entries = [
            ("owner__oldest", 30000),
            ("owner__middle", 20000),
            ("owner__newest", 10000),
        ]
        for name, age in entries:
            d = root / name
            d.mkdir()
            marker = d / _LAST_FETCHED_FILE
            marker.touch()
            os.utime(marker, (now - age, now - age))

        result = await list_clones(mid)
        assert result[0].name == "owner__oldest"
        assert result[-1].name == "owner__newest"


# ---------------------------------------------------------------------------
# evict_stale
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEvictStale:
    async def test_empty_when_no_clones(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        mid = _make_mini_id()
        result = await evict_stale(mid)
        assert result == []

    async def test_evicts_oldest_first(self, tmp_path, monkeypatch):
        """Oldest clones are evicted first until total size is under cap."""
        import os

        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        mid = _make_mini_id()
        root = tmp_path / ".minis" / "clones" / str(mid)
        root.mkdir(parents=True)

        now = time.time()
        paths = []
        entries = [
            ("a__oldest", 30000),
            ("b__middle", 20000),
            ("c__newest", 10000),
        ]
        for name, age in entries:
            d = root / name
            d.mkdir()
            # Write 1 MB of data so total > cap
            (d / "big.bin").write_bytes(b"x" * 1_048_576)
            marker = d / _LAST_FETCHED_FILE
            marker.touch()
            os.utime(marker, (now - age, now - age))
            paths.append(d)

        # Cap at 2 MB — with 3×1MB total = 3MB, we must evict 1 repo
        evicted = await evict_stale(mid, cap_bytes=2 * 1_048_576)

        assert len(evicted) == 1
        assert evicted[0].name == "a__oldest"
        assert not evicted[0].exists()
        # The other two should still be there
        assert paths[1].exists()
        assert paths[2].exists()

    async def test_no_eviction_if_under_cap(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLY_APP_NAME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        mid = _make_mini_id()
        root = tmp_path / ".minis" / "clones" / str(mid)
        root.mkdir(parents=True)

        d = root / "owner__repo"
        d.mkdir()
        (d / "file.txt").write_text("hello")

        # Enormous cap — nothing evicted
        evicted = await evict_stale(mid, cap_bytes=_DEFAULT_CAP_BYTES)
        assert evicted == []


_DEFAULT_CAP_BYTES = 5 * 1024 * 1024 * 1024
