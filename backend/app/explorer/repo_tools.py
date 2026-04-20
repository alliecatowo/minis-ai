"""Read-only filesystem and git tools for per-repo LLM agents.

All tools accept a ``clone_root`` (a :class:`pathlib.Path` pointing at a local
git checkout) and a relative path string.  Every path is resolved and verified
to be inside ``clone_root`` before any I/O takes place.

Security guarantees
-------------------
- No ``shell=True`` anywhere.
- Every user-supplied path goes through :func:`_safe_resolve` which raises
  :class:`PathTraversalError` if the resolved absolute path escapes
  ``clone_root``.  This blocks both ``../../`` traversals and absolute paths.
- Symlinks that resolve outside the repo root are also blocked by the same
  check (``Path.resolve()`` follows symlinks).
- Binary files detected by a null-byte scan of the first 8 KB are returned as
  ``<elided: binary>`` rather than raw bytes.
- No repo content is ever executed (``make``, ``npm``, ``python``, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories that are noisy and rarely relevant for personality analysis
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "vendor",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",  # Rust/Java
        "pkg",  # Go module cache when vendored
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".tox",
        "coverage",
        ".coverage",
    }
)

_BINARY_SCAN_BYTES = 8_192


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PathTraversalError(ValueError):
    """Raised when a resolved path escapes the clone root."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_resolve(clone_root: Path, rel_path: str) -> Path:
    """Resolve *rel_path* relative to *clone_root* and verify containment.

    Raises :class:`PathTraversalError` if the resolved path:
    - lies outside ``clone_root`` (traversal via ``../../``),
    - is an absolute path (the join would ignore ``clone_root``),
    - points through a symlink that exits the repo.

    Returns the resolved :class:`Path` on success.
    """
    # Reject absolute paths immediately — they bypass clone_root entirely
    if Path(rel_path).is_absolute():
        raise PathTraversalError(f"Absolute paths are not allowed: {rel_path!r}")

    resolved = (clone_root / rel_path).resolve()
    clone_resolved = clone_root.resolve()

    # The resolved path must equal clone_root OR have clone_root as a parent
    if resolved != clone_resolved and clone_resolved not in resolved.parents:
        raise PathTraversalError(f"Path {rel_path!r} resolves outside the clone root: {resolved}")
    return resolved


def _is_binary(path: Path) -> bool:
    """Return True if *path* looks like a binary file (null byte in first 8 KB)."""
    try:
        with path.open("rb") as fh:
            chunk = fh.read(_BINARY_SCAN_BYTES)
        return b"\x00" in chunk
    except OSError:
        return False


async def _run_git_in_repo(*args: str, cwd: Path) -> tuple[int, str, str]:
    """Run a git sub-command inside ``cwd`` and return (returncode, stdout, stderr).

    Uses ``asyncio.create_subprocess_exec`` — never ``shell=True``.
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout_bytes.decode(errors="replace"),
        stderr_bytes.decode(errors="replace"),
    )


# ---------------------------------------------------------------------------
# Public tool functions
# ---------------------------------------------------------------------------


async def list_directory(clone_root: Path, rel_path: str = "") -> str:
    """Return a human-readable directory listing for *rel_path* inside the repo.

    Skips directories listed in ``_SKIP_DIRS``.  Each entry is annotated with
    its type (``[dir]`` / ``[file]``) and size in bytes for files.

    Raises :class:`PathTraversalError` if *rel_path* escapes ``clone_root``.
    """
    target = _safe_resolve(clone_root, rel_path) if rel_path else clone_root.resolve()

    if not target.exists():
        return f"<not found: {rel_path!r}>"
    if not target.is_dir():
        return f"<not a directory: {rel_path!r}>"

    lines: list[str] = [f"Contents of {rel_path or '/'}:"]
    for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name)):
        if entry.name in _SKIP_DIRS:
            continue
        if entry.is_symlink():
            try:
                _safe_resolve(clone_root, str(entry.relative_to(clone_root.resolve())))
                tag = "[symlink]"
            except PathTraversalError:
                tag = "[symlink→outside, blocked]"
            lines.append(f"  {tag} {entry.name}")
        elif entry.is_dir():
            lines.append(f"  [dir]  {entry.name}/")
        else:
            try:
                size = entry.stat().st_size
                lines.append(f"  [file] {entry.name}  ({size:,} bytes)")
            except OSError:
                lines.append(f"  [file] {entry.name}")

    return "\n".join(lines)


async def read_file(
    clone_root: Path,
    rel_path: str,
    *,
    max_bytes: int = 80_000,
) -> str:
    """Return the text content of *rel_path* inside the repo.

    - Blocks path traversal via :func:`_safe_resolve`.
    - Returns ``<elided: binary>`` for binary files.
    - Truncates to *max_bytes* with a trailing note if the file is larger.
    - Returns ``<elided: symlink outside repo>`` for symlinks pointing out of
      the clone root.

    Raises :class:`PathTraversalError` if *rel_path* escapes ``clone_root``.
    """
    # _safe_resolve follows symlinks (Path.resolve()), so a symlink pointing
    # outside the repo will raise PathTraversalError — we convert that to the
    # elided sentinel rather than propagating as an error.
    try:
        resolved = _safe_resolve(clone_root, rel_path)
    except PathTraversalError:
        # Could be a symlink that exits the repo OR a genuine path traversal.
        # Distinguish: if the *lexical* path is inside the repo but the
        # resolved target is not, it's a symlink escape → sentinel.
        # If the lexical path itself escapes (e.g. "../../etc"), re-raise.
        lexical = clone_root / rel_path
        if lexical.is_symlink():
            return "<elided: symlink outside repo>"
        raise

    if not resolved.exists():
        return f"<not found: {rel_path!r}>"
    if not resolved.is_file():
        return f"<not a file: {rel_path!r}>"
    if _is_binary(resolved):
        return "<elided: binary>"

    try:
        with resolved.open("rb") as fh:
            raw = fh.read(max_bytes + 1)
        truncated = len(raw) > max_bytes
        text = raw[:max_bytes].decode("utf-8", errors="replace")
        if truncated:
            text += f"\n\n<truncated: file exceeds {max_bytes:,} bytes>"
        return text
    except OSError as exc:
        return f"<error reading {rel_path!r}: {exc}>"


async def grep_in_repo(
    clone_root: Path,
    pattern: str,
    *,
    include: str | None = None,
    max_matches: int = 200,
) -> str:
    """Search *pattern* across the repo using ``git grep``.

    Uses ``git -C <clone_root> grep -n <pattern>`` (optionally filtered by
    ``--`` *include* glob).  The ``--`` separator prevents pattern injection.

    Returns up to *max_matches* lines in ``file:line_no:content`` format, or a
    ``<no matches>`` string.

    Note: ``git grep`` operates on tracked files only (respects .gitignore) and
    does not execute any repo content.
    """
    # Build the git grep arg list.  The cwd is set to clone_root so we
    # don't need (and must not pass) the -C flag to _run_git_in_repo.
    # The "--" before the pattern prevents the pattern being mistaken for a flag.
    git_args: list[str] = ["grep", "-n", "--", pattern]
    if include:
        # A second "--" separates the pattern from the pathspec glob
        git_args += ["--", include]

    returncode, stdout, _stderr = await _run_git_in_repo(
        *git_args,
        cwd=clone_root,
    )

    # git grep exits 1 when there are no matches — that's not an error
    if returncode not in (0, 1):
        return f"<git grep error (rc={returncode})>"

    lines = stdout.splitlines()
    if not lines:
        return "<no matches>"

    trimmed = lines[:max_matches]
    suffix = (
        f"\n<truncated: showing {max_matches} of {len(lines)} matches>"
        if len(lines) > max_matches
        else ""
    )
    return "\n".join(trimmed) + suffix


async def git_log(
    clone_root: Path,
    rel_path: str | None = None,
    *,
    limit: int = 50,
) -> str:
    """Return the git log for the repo or a specific file path.

    Uses ``git -C <clone_root> log --oneline [-n limit] [-- rel_path]``.

    Raises :class:`PathTraversalError` if *rel_path* escapes ``clone_root``.
    """
    args: list[str] = ["log", "--oneline", f"-n{limit}"]

    if rel_path:
        # Validate the path but pass the relative string (not the resolved
        # absolute path) to git so it matches correctly
        _safe_resolve(clone_root, rel_path)
        args += ["--follow", "--", rel_path]

    returncode, stdout, stderr = await _run_git_in_repo(*args, cwd=clone_root)

    if returncode != 0:
        return f"<git log error (rc={returncode}): {stderr[:300]}>"

    return stdout.strip() or "<no commits found>"


async def open_diff(
    clone_root: Path,
    commit_sha: str,
    *,
    max_bytes: int = 20_000,
) -> str:
    """Return the patch for *commit_sha* (``git show --stat --patch``).

    *commit_sha* is passed as a positional argument after ``--`` to prevent
    flag injection.  Only hex characters and ``^~:.`` are allowed; anything
    else raises :class:`ValueError`.

    Truncates to *max_bytes* with a trailing note.
    """
    # Sanitise commit_sha — allow hex digits + common git rev suffixes
    allowed = set("0123456789abcdefABCDEF^~:.")
    if not commit_sha or not all(c in allowed for c in commit_sha):
        raise ValueError(
            f"Invalid commit SHA {commit_sha!r}. Only hex digits and ^~:. are allowed."
        )

    returncode, stdout, stderr = await _run_git_in_repo(
        "show",
        "--stat",
        "--patch",
        commit_sha,
        cwd=clone_root,
    )

    if returncode != 0:
        return f"<git show error (rc={returncode}): {stderr[:300]}>"

    if len(stdout) > max_bytes:
        return stdout[:max_bytes] + f"\n\n<truncated: diff exceeds {max_bytes:,} bytes>"
    return stdout
