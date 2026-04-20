"""Persistent local clone manager for per-repo exploration.

Each mini gets its own clone root so that multiple minis can be processed in
parallel without path collisions.  Clone paths are stable across pipeline runs
(incremental ingestion — ALLIE-374): we refresh an existing clone rather than
re-cloning from scratch.

Environment detection
---------------------
- Fly.io  : ``FLY_APP_NAME`` env var present  → ``/data/clones/{mini_id}/{slug}``
- Local   : fallback                           → ``~/.minis/clones/{mini_id}/{slug}``

Security
--------
- No ``shell=True`` anywhere.
- ``GITHUB_TOKEN`` is injected into the clone URL; the raw token is never logged.
- Paths are constructed from trusted inputs (mini_id UUID + validated owner/repo
  strings); no user-controlled path expansion.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from uuid import UUID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CLONE_DEPTH = 50
_STALE_SECONDS = 30 * 24 * 60 * 60  # 30 days
_DEFAULT_CAP_BYTES = 5 * 1024 * 1024 * 1024  # 5 GiB
_LAST_FETCHED_FILE = ".last_fetched"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _clones_root() -> Path:
    """Return the root directory for all clones, based on runtime environment."""
    if os.environ.get("FLY_APP_NAME"):
        return Path("/data/clones")
    return Path.home() / ".minis" / "clones"


def clone_path(mini_id: UUID, owner: str, repo: str) -> Path:
    """Return the deterministic local path for ``owner/repo`` under ``mini_id``.

    The directory separator in ``owner/repo`` is replaced with ``__`` so the
    full name can be stored as a single directory component.

    Example::

        clone_path(uuid, "torvalds", "linux")
        # ~/.minis/clones/<uuid>/torvalds__linux
    """
    slug = f"{owner}__{repo}"
    return _clones_root() / str(mini_id) / slug


# ---------------------------------------------------------------------------
# Low-level subprocess helpers
# ---------------------------------------------------------------------------


async def _run_git(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a git sub-command and return ``(returncode, stdout, stderr)``.

    Uses ``asyncio.create_subprocess_exec`` (never ``shell=True``).
    The ``GITHUB_TOKEN`` must already be embedded in the URL by the caller;
    it is NOT passed as an argument here.
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout_bytes.decode(errors="replace"),
        stderr_bytes.decode(errors="replace"),
    )


def _touch_last_fetched(path: Path) -> None:
    """Update (or create) the ``.last_fetched`` timestamp file inside *path*."""
    marker = path / _LAST_FETCHED_FILE
    marker.touch()


def _last_fetched_at(path: Path) -> float:
    """Return epoch seconds of the last fetch, or 0.0 if never recorded."""
    marker = path / _LAST_FETCHED_FILE
    if marker.exists():
        return marker.stat().st_mtime
    # Fall back to FETCH_HEAD mtime if the marker file is absent (e.g. legacy clone)
    fetch_head = path / ".git" / "FETCH_HEAD"
    if fetch_head.exists():
        return fetch_head.stat().st_mtime
    return 0.0


def _dir_size(path: Path) -> int:
    """Return total byte size of all files under *path* (non-recursive symlinks skipped)."""
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file(follow_symlinks=False):
            try:
                total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def ensure_clone(
    mini_id: UUID,
    owner: str,
    repo: str,
    *,
    depth: int = _CLONE_DEPTH,
) -> Path:
    """Return a local clone path for ``owner/repo``, creating it if necessary.

    Behaviour:
    - If the clone directory already exists **and** was fetched less than 30
      days ago, return immediately without any network I/O (incremental
      ingestion — the existing checkout is fresh enough).
    - If the directory exists but is stale, skip full re-clone; the caller
      should call :func:`refresh_clone` explicitly when needed.
    - If the directory does not exist, run a shallow ``git clone``.

    The GITHUB_TOKEN (from the ``GITHUB_TOKEN`` env var) is injected into the
    HTTPS clone URL so that private repos are accessible.  The token is
    **never** logged.
    """
    path = clone_path(mini_id, owner, repo)

    if path.exists():
        age = time.time() - _last_fetched_at(path)
        if age < _STALE_SECONDS:
            logger.debug("clone_manager: fresh clone exists, skipping — %s/%s", owner, repo)
            return path
        logger.debug(
            "clone_manager: clone exists but is stale (%.0f days), returning as-is — %s/%s",
            age / 86400,
            owner,
            repo,
        )
        return path

    path.parent.mkdir(parents=True, exist_ok=True)

    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        clone_url = f"https://{token}@github.com/{owner}/{repo}.git"
    else:
        clone_url = f"https://github.com/{owner}/{repo}.git"

    # Log the URL with the token scrubbed
    safe_url = f"https://github.com/{owner}/{repo}.git"
    logger.info("clone_manager: cloning %s (depth=%d) → %s", safe_url, depth, path)

    returncode, _stdout, stderr = await _run_git(
        "clone",
        "--depth",
        str(depth),
        "--filter=blob:limit=1M",
        "--single-branch",
        clone_url,
        str(path),
    )

    if returncode != 0:
        # Scrub token from error message before logging
        safe_stderr = stderr.replace(token, "***") if token else stderr
        logger.error("clone_manager: git clone failed (rc=%d): %s", returncode, safe_stderr)
        raise RuntimeError(
            f"git clone failed for {owner}/{repo} (rc={returncode}): {safe_stderr[:500]}"
        )

    _touch_last_fetched(path)
    return path


async def refresh_clone(path: Path) -> None:
    """Fetch latest commits for an existing clone (``git fetch --prune``)."""
    if not path.exists():
        raise FileNotFoundError(f"clone_manager: clone path does not exist: {path}")

    token = os.environ.get("GITHUB_TOKEN", "")
    logger.info("clone_manager: refreshing clone at %s", path)

    returncode, _stdout, stderr = await _run_git(
        "-C",
        str(path),
        "fetch",
        "--prune",
        "--depth",
        str(_CLONE_DEPTH),
    )

    if returncode != 0:
        safe_stderr = stderr.replace(token, "***") if token else stderr
        logger.warning("clone_manager: git fetch failed (rc=%d): %s", returncode, safe_stderr)
        raise RuntimeError(f"git fetch failed at {path} (rc={returncode}): {safe_stderr[:500]}")

    _touch_last_fetched(path)


async def list_clones(mini_id: UUID) -> list[Path]:
    """Return all clone directories for *mini_id*, sorted by last_fetched_at ascending."""
    root = _clones_root() / str(mini_id)
    if not root.exists():
        return []
    clones = [p for p in root.iterdir() if p.is_dir()]
    clones.sort(key=_last_fetched_at)
    return clones


async def evict_stale(
    mini_id: UUID,
    cap_bytes: int = _DEFAULT_CAP_BYTES,
) -> list[Path]:
    """Delete the oldest clones for *mini_id* until total size is under *cap_bytes*.

    Returns the list of paths that were removed.
    """
    clones = await list_clones(mini_id)
    if not clones:
        return []

    total = sum(_dir_size(p) for p in clones)
    evicted: list[Path] = []

    # clones is sorted oldest-first by list_clones
    for clone in clones:
        if total <= cap_bytes:
            break
        size = _dir_size(clone)
        logger.info(
            "clone_manager: evicting %s (%.1f MB, total %.1f / %.1f GB cap)",
            clone,
            size / 1024 / 1024,
            total / 1024 / 1024 / 1024,
            cap_bytes / 1024 / 1024 / 1024,
        )
        shutil.rmtree(clone, ignore_errors=True)
        total -= size
        evicted.append(clone)

    return evicted
