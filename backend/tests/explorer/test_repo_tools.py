"""Unit tests for backend/app/explorer/repo_tools.py.

Uses a real git repository created in tmp_path so that git commands produce
genuine output.  No network access; no real LLM calls.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from app.explorer.repo_tools import (
    PathTraversalError,
    _safe_resolve,
    git_log,
    grep_in_repo,
    list_directory,
    open_diff,
    read_file,
)


# ---------------------------------------------------------------------------
# Fixture: minimal real git repository
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with two commits and known content."""
    root = tmp_path / "testrepo"
    root.mkdir()

    # Configure git identity (required in CI)
    env = {**os.environ, "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1"}

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"git {args} failed: {result.stderr}"
        return result.stdout.strip()

    git("init")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test User")

    # Commit 1: add hello.py and README.md
    (root / "hello.py").write_text("def greet(name):\n    return f'Hello, {name}!'\n")
    (root / "README.md").write_text("# Test Repo\nA sample repository.\n")
    (root / "subdir").mkdir()
    (root / "subdir" / "util.py").write_text("def helper():\n    pass\n")
    git("add", ".")
    git("commit", "-m", "Initial commit")

    # Capture first commit SHA
    first_sha = git("rev-parse", "HEAD")
    (root / ".first_sha").write_text(first_sha)

    # Commit 2: add binary file + data file
    (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00" + b"\x00" * 100)
    (root / "data.txt").write_text("line one\nline two\nline three\n")
    git("add", ".")
    git("commit", "-m", "Add binary and data files")

    return root


# ---------------------------------------------------------------------------
# _safe_resolve — path traversal guard
# ---------------------------------------------------------------------------


class TestSafeResolve:
    def test_valid_relative_path(self, repo: Path):
        resolved = _safe_resolve(repo, "hello.py")
        assert resolved == (repo / "hello.py").resolve()

    def test_valid_nested_path(self, repo: Path):
        resolved = _safe_resolve(repo, "subdir/util.py")
        assert resolved.name == "util.py"

    def test_traversal_dotdot_raises(self, repo: Path):
        with pytest.raises(PathTraversalError):
            _safe_resolve(repo, "../../etc/passwd")

    def test_traversal_absolute_raises(self, repo: Path):
        with pytest.raises(PathTraversalError):
            _safe_resolve(repo, "/etc/passwd")

    def test_root_path_empty_string(self, repo: Path):
        """Empty rel_path is not passed to _safe_resolve in normal usage."""
        # A "." refers to the clone_root itself — not a traversal
        resolved = _safe_resolve(repo, ".")
        assert resolved == repo.resolve()

    def test_dotdot_in_middle_raises(self, repo: Path):
        with pytest.raises(PathTraversalError):
            _safe_resolve(repo, "subdir/../../secret")


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListDirectory:
    async def test_root_listing(self, repo: Path):
        output = await list_directory(repo, "")
        assert "hello.py" in output
        assert "README.md" in output
        assert "subdir" in output

    async def test_subdirectory_listing(self, repo: Path):
        output = await list_directory(repo, "subdir")
        assert "util.py" in output

    async def test_skip_dirs_excluded(self, repo: Path):
        """node_modules and .git must not appear in listings."""
        (repo / "node_modules").mkdir()
        (repo / "node_modules" / "pkg").mkdir()
        output = await list_directory(repo, "")
        assert "node_modules" not in output

    async def test_missing_path_returns_not_found(self, repo: Path):
        output = await list_directory(repo, "nonexistent_dir")
        assert "not found" in output

    async def test_traversal_raises(self, repo: Path):
        with pytest.raises(PathTraversalError):
            await list_directory(repo, "../outside")

    async def test_symlink_outside_blocked(self, repo: Path, tmp_path: Path):
        """A symlink pointing outside the repo is labelled as blocked."""
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        link = repo / "evil_link"
        link.symlink_to(outside)
        output = await list_directory(repo, "")
        assert "outside" in output or "blocked" in output


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestReadFile:
    async def test_reads_known_content(self, repo: Path):
        content = await read_file(repo, "hello.py")
        assert "def greet" in content
        assert "Hello" in content

    async def test_respects_max_bytes(self, repo: Path):
        """File content is truncated at max_bytes."""
        content = await read_file(repo, "hello.py", max_bytes=5)
        assert "truncated" in content

    async def test_binary_elided(self, repo: Path):
        content = await read_file(repo, "image.png")
        assert content == "<elided: binary>"

    async def test_missing_file_returns_not_found(self, repo: Path):
        content = await read_file(repo, "does_not_exist.py")
        assert "not found" in content

    async def test_traversal_dotdot_raises(self, repo: Path):
        with pytest.raises(PathTraversalError):
            await read_file(repo, "../../etc/passwd")

    async def test_traversal_absolute_raises(self, repo: Path):
        with pytest.raises(PathTraversalError):
            await read_file(repo, "/etc/hostname")

    async def test_symlink_outside_repo_elided(self, repo: Path, tmp_path: Path):
        """Symlink pointing outside the repo returns the elided sentinel."""
        secret = tmp_path / "passwd"
        secret.write_text("root:x:0:0:root:/root:/bin/bash")
        link = repo / "evil.txt"
        link.symlink_to(secret)
        content = await read_file(repo, "evil.txt")
        assert content == "<elided: symlink outside repo>"

    async def test_nested_file(self, repo: Path):
        content = await read_file(repo, "subdir/util.py")
        assert "def helper" in content


# ---------------------------------------------------------------------------
# grep_in_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGrepInRepo:
    async def test_finds_pattern(self, repo: Path):
        output = await grep_in_repo(repo, "greet")
        assert "hello.py" in output
        assert "greet" in output

    async def test_no_matches(self, repo: Path):
        output = await grep_in_repo(repo, "zzz_no_match_xyz")
        assert "no matches" in output

    async def test_max_matches_truncation(self, repo: Path):
        """Results are capped at max_matches."""
        # Write a file with many matching lines
        many_lines = "\n".join(f"needle line {i}" for i in range(100))
        (repo / "big.txt").write_text(many_lines)
        subprocess.run(["git", "-C", str(repo), "add", "big.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "add big file"],
            check=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t",
            },
        )
        output = await grep_in_repo(repo, "needle", max_matches=5)
        assert "truncated" in output

    async def test_include_glob_filter(self, repo: Path):
        """include glob limits search to matching files."""
        output = await grep_in_repo(repo, "line", include="*.txt")
        assert "data.txt" in output
        # Should not include Python files for a .txt-only search
        assert "hello.py" not in output


# ---------------------------------------------------------------------------
# git_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGitLog:
    async def test_returns_commits(self, repo: Path):
        output = await git_log(repo)
        assert "Initial commit" in output

    async def test_limit_respected(self, repo: Path):
        output = await git_log(repo, limit=1)
        lines = [line for line in output.splitlines() if line.strip()]
        assert len(lines) == 1

    async def test_log_for_specific_file(self, repo: Path):
        output = await git_log(repo, "hello.py")
        assert "Initial commit" in output
        # image.png was added in a different commit
        assert "binary" not in output

    async def test_traversal_raises(self, repo: Path):
        with pytest.raises(PathTraversalError):
            await git_log(repo, "../../outside.py")


# ---------------------------------------------------------------------------
# open_diff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOpenDiff:
    def _get_sha(self, repo: Path, n: int = 0) -> str:
        """Return nth commit SHA (0 = HEAD)."""
        result = subprocess.run(
            ["git", "-C", str(repo), "log", "--format=%H"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip().splitlines()[n]

    async def test_returns_patch_for_known_commit(self, repo: Path):
        sha = self._get_sha(repo, n=1)  # Initial commit
        output = await open_diff(repo, sha)
        assert "hello.py" in output or "Initial commit" in output

    async def test_truncation(self, repo: Path):
        sha = self._get_sha(repo, 0)
        output = await open_diff(repo, sha, max_bytes=10)
        assert "truncated" in output

    async def test_invalid_sha_raises_valueerror(self, repo: Path):
        with pytest.raises(ValueError, match="Invalid commit SHA"):
            await open_diff(repo, "../../../evil")

    async def test_invalid_sha_with_spaces_raises(self, repo: Path):
        with pytest.raises(ValueError, match="Invalid commit SHA"):
            await open_diff(repo, "abc; rm -rf /")

    async def test_short_sha(self, repo: Path):
        full_sha = self._get_sha(repo, 0)
        short_sha = full_sha[:7]
        output = await open_diff(repo, short_sha)
        # Should succeed and contain diff content
        assert len(output) > 0
        assert "<git show error" not in output
