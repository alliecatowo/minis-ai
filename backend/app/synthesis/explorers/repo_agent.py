"""Per-repository PydanticAI agent for local-clone code exploration.

Each RepoAgent operates on a single locally-cloned git repository and writes
findings directly to the Evidence DB tables via the standard explorer tool
suite.  The agent uses the M1 read-only filesystem/git primitives from
``app.explorer.repo_tools`` plus the DB-write tools from
``app.synthesis.explorers.tools``.

Usage::

    agent = RepoAgent(mini_id=..., db_session=..., session_factory=...)
    report = await agent.run(owner="torvalds", repo="linux", clone_root=Path(...))
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import insert, update

from app.core.agent import AgentTool, run_agent
from app.core.models import ModelTier, get_model
from app.explorer.repo_tools import (
    git_log,
    grep_in_repo,
    list_directory,
    open_diff,
    read_file,
)
from app.models.evidence import ExplorerProgress
from app.synthesis.explorers.tools import build_explorer_tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment-driven knobs (all tuneable via env vars)
# ---------------------------------------------------------------------------

# Maximum repos to clone and explore per mini (default 5).
REPO_AGENT_MAX: int = int(os.environ.get("REPO_AGENT_MAX", "5"))

# Maximum concurrent clone + explore tasks.
REPO_AGENT_CONCURRENCY: int = int(os.environ.get("REPO_AGENT_CONCURRENCY", "4"))

# Max git-repo size in KB that we're willing to clone (default 200 MB).
REPO_SIZE_LIMIT_KB: int = int(os.environ.get("REPO_SIZE_LIMIT_KB", str(200 * 1024)))

# Feature flag — set ENABLE_LOCAL_CLONE_EXPLORER=true to activate fan-out.
ENABLE_LOCAL_CLONE_EXPLORER: bool = (
    os.environ.get("ENABLE_LOCAL_CLONE_EXPLORER", "false").lower() == "true"
)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_REPO_AGENT_SYSTEM_PROMPT = """\
You are a code repository explorer. Your mission is to understand the AUTHOR of \
this repository from the inside — their coding style, technical opinions, habits, \
and the patterns that define how they think and work.

## Starting sequence
1. Call list_directory("") to see the root structure.
2. Call read_file("README.md") or similar top-level docs to understand what the \
   project does and how the author describes it.
3. Explore key source directories with read_file: look at 3–5 representative \
   source files to understand naming, structure, and style.
4. Use grep_in_repo to search for patterns that reveal style:
   - Error handling: grep for "except", "unwrap()", "if err != nil", "raise"
   - Comments: grep for "# " or "//" to see how (and whether) they comment
   - TODOs/FIXMEs: reveal tech debt awareness and honesty
   - Logging patterns: logger.debug vs print vs silence
5. Use git_log to see how they iterate — commit message style is a rich signal.
6. Use open_diff on 2–3 interesting commits to see what a "unit of work" looks like.

## What to extract
Save at least 5–10 distinctive findings per repo. Look for:
- **Coding style**: functional vs OO, verbosity, naming conventions, file structure
- **Error handling philosophy**: defensive vs optimistic, explicit vs implicit
- **Testing habits**: presence/absence of tests, test style, what they test
- **Documentation style**: README quality, inline comments, docstrings
- **Commit discipline**: atomic commits vs dump-all, commit message quality
- **Technical opinions**: dependency choices, architecture patterns, what they avoid
- **Specific skills**: languages, frameworks, tools evident in the codebase

When you find a revealing pattern, save it:
- **save_finding**: for personality/style/values insights (confidence 0.6–0.9)
- **save_memory**: for factual skills/projects/tech stack
- **save_quote**: for exact code snippets or comments that illustrate a point
- **save_knowledge_node** / **save_knowledge_edge**: for skill graph
- **save_principle**: for clear decision rules ("they always X when Y")

## Standards
- Quote REAL code when illustrating a point — not paraphrases.
- Distinguish between code the author wrote and boilerplate/generated code.
- Tier 1 truth: what the code DOES. Tier 2: what the README SAYS. Flag conflicts.
- Finish when you have explored enough to produce 5–10 distinctive findings.
  Do NOT pad with weak observations just to hit 10.
- Call finish() with a summary when done.
"""

# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------


def build_repo_tools(
    clone_root: Path,
    slug: str,
    mini_id: str,
    db_session: Any,
    session_factory: Any = None,
) -> list[AgentTool]:
    """Build the full tool suite for a RepoAgent.

    Composes:
    - Read-only FS/git tools (from app.explorer.repo_tools), closed over clone_root.
    - DB write tools (from app.synthesis.explorers.tools), with source_type set
      to ``github_repo:<slug>``.

    Parameters
    ----------
    clone_root:
        Local filesystem path of the cloned repository.
    slug:
        Human-readable identifier for this repo, e.g. ``"torvalds__linux"``.
        Used as the suffix in ``source_type="github_repo:<slug>"``.
    mini_id:
        UUID string of the mini being analyzed.
    db_session:
        Async SQLAlchemy session for read operations.
    session_factory:
        Async session factory for isolated write operations.
    """
    source_type = f"github_repo:{slug}"

    # --- FS / git read tools (closed over clone_root) ---

    async def _list_directory(path: str = "") -> str:
        return await list_directory(clone_root, path)

    async def _read_file(path: str, max_bytes: int = 25000) -> str:
        return await read_file(clone_root, path, max_bytes=max_bytes)

    async def _grep_in_repo(
        pattern: str,
        include: str | None = None,
        max_matches: int = 50,
    ) -> str:
        return await grep_in_repo(clone_root, pattern, include=include, max_matches=max_matches)

    async def _git_log(path: str = "", limit: int = 20) -> str:
        return await git_log(clone_root, path or None, limit=limit)

    async def _open_diff(commit_sha: str, max_bytes: int = 10000) -> str:
        return await open_diff(clone_root, commit_sha, max_bytes=max_bytes)

    fs_tools: list[AgentTool] = [
        AgentTool(
            name="list_directory",
            description=(
                "List files and directories at a path inside the repository. "
                "Start with '' (empty string) for the root. Skips build artifacts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path inside the repo ('' = root).",
                    },
                },
                "required": [],
            },
            handler=_list_directory,
        ),
        AgentTool(
            name="read_file",
            description=(
                "Read the text content of a source file in the repository. "
                "Returns '<elided: binary>' for binary files. Truncates large files."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path (e.g. 'src/main.py').",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": "Max bytes to read (default 25000).",
                    },
                },
                "required": ["path"],
            },
            handler=_read_file,
        ),
        AgentTool(
            name="grep_in_repo",
            description=(
                "Search the repository for a pattern using git grep. "
                "Returns file:line:content matches. Does not execute code."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex/literal pattern to search for.",
                    },
                    "include": {
                        "type": "string",
                        "description": "File glob to restrict search (e.g. '*.py').",
                    },
                    "max_matches": {
                        "type": "integer",
                        "description": "Max results to return (default 50).",
                    },
                },
                "required": ["pattern"],
            },
            handler=_grep_in_repo,
        ),
        AgentTool(
            name="git_log",
            description=(
                "Show git commit history for the repo or a specific file. "
                "Returns one-line summary per commit."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path to filter by ('' = whole repo).",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max commits to show (default 20).",
                    },
                },
                "required": [],
            },
            handler=_git_log,
        ),
        AgentTool(
            name="open_diff",
            description=(
                "Show the patch for a specific commit (git show --stat --patch). "
                "Reveals what actually changed — the ground truth of a commit message."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "commit_sha": {
                        "type": "string",
                        "description": "Full or abbreviated commit SHA.",
                    },
                    "max_bytes": {
                        "type": "integer",
                        "description": "Max bytes of diff to return (default 10000).",
                    },
                },
                "required": ["commit_sha"],
            },
            handler=_open_diff,
        ),
    ]

    # --- DB write tools (from tools.py, source_type = "github_repo:<slug>") ---
    db_tools = build_explorer_tools(
        mini_id=mini_id,
        source_type=source_type,
        db_session=db_session,
        session_factory=session_factory,
    )

    # Exclude read tools from the DB set (browse_evidence, search_evidence,
    # read_item) — those don't apply to local-clone exploration.  Keep all
    # write tools: save_*, mark_explored, get_progress, finish.
    _READ_ONLY_TOOLS = {"browse_evidence", "search_evidence", "read_item", "mark_explored"}
    write_db_tools = [t for t in db_tools if t.name not in _READ_ONLY_TOOLS]

    return fs_tools + write_db_tools


# ---------------------------------------------------------------------------
# RepoAgent
# ---------------------------------------------------------------------------


class RepoAgent:
    """Autonomous agent that explores a single git repository clone.

    Instances are created fresh per repo (no shared state between repos).
    The agent writes findings directly to DB via the tool suite built by
    ``build_repo_tools()``.
    """

    def __init__(
        self,
        mini_id: str | UUID,
        db_session: Any,
        session_factory: Any = None,
        model: str | None = None,
    ) -> None:
        self.mini_id = str(mini_id)
        self.db_session = db_session
        self.session_factory = session_factory
        self.model = model or get_model(ModelTier.STANDARD)

    async def run(
        self,
        owner: str,
        repo: str,
        clone_root: Path,
    ) -> dict[str, Any]:
        """Explore ``clone_root`` and persist findings for ``owner/repo``.

        Returns a summary dict with ``slug``, ``turns_used``, ``status``.
        """
        slug = f"{owner}__{repo}"
        source_type = f"github_repo:{slug}"

        logger.info(
            "repo_agent: starting — mini_id=%s slug=%s clone=%s",
            self.mini_id,
            slug,
            clone_root,
        )

        # Create / update ExplorerProgress row for this repo
        await self._upsert_progress(source_type, status="running")

        tools = build_repo_tools(
            clone_root=clone_root,
            slug=slug,
            mini_id=self.mini_id,
            db_session=self.db_session,
            session_factory=self.session_factory,
        )

        user_prompt = (
            f"Explore the repository '{owner}/{repo}' at {clone_root}. "
            "Start with the root directory, then dive into key source files. "
            "Save at least 5 distinctive findings about the author's coding style and values."
        )

        t_start = asyncio.get_event_loop().time()

        try:
            result = await run_agent(
                system_prompt=_REPO_AGENT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                tools=tools,
                max_turns=40,
                model=self.model,
                tool_choice_strategy="required_until_finish",
                finish_tool_name="finish",
            )

            elapsed_ms = int((asyncio.get_event_loop().time() - t_start) * 1000)

            logger.info(
                "repo_agent.finished — mini_id=%s slug=%s turns=%d elapsed_ms=%d",
                self.mini_id,
                slug,
                result.turns_used,
                elapsed_ms,
            )

            # Count findings saved (from tool_outputs tracking)
            evidence_items_saved = sum(
                len(v) for k, v in result.tool_outputs.items() if k.startswith("save_")
            )

            logger.info(
                "repo_agent.finding_saved — mini_id=%s slug=%s evidence_items=%d",
                self.mini_id,
                slug,
                evidence_items_saved,
            )

            await self._upsert_progress(source_type, status="completed")

            return {
                "slug": slug,
                "turns_used": result.turns_used,
                "status": "completed",
                "elapsed_ms": elapsed_ms,
                "evidence_items_saved": evidence_items_saved,
            }

        except Exception as exc:
            elapsed_ms = int((asyncio.get_event_loop().time() - t_start) * 1000)
            logger.error(
                "repo_agent.failed — mini_id=%s slug=%s error=%s elapsed_ms=%d",
                self.mini_id,
                slug,
                exc,
                elapsed_ms,
            )
            await self._upsert_progress(source_type, status="failed")
            return {
                "slug": slug,
                "turns_used": 0,
                "status": "failed",
                "elapsed_ms": elapsed_ms,
                "error": str(exc),
            }

    async def _upsert_progress(self, source_type: str, status: str) -> None:
        """Create or update ExplorerProgress for this (mini_id, source_type) pair."""
        now = datetime.datetime.now(datetime.timezone.utc)

        async def _do(session: Any) -> None:
            # Try update first
            update_values: dict[str, Any] = {"status": status}
            if status == "completed":
                update_values["finished_at"] = now
            elif status == "running":
                update_values["started_at"] = now

            stmt_update = (
                update(ExplorerProgress)
                .where(
                    ExplorerProgress.mini_id == self.mini_id,
                    ExplorerProgress.source_type == source_type,
                )
                .values(**update_values)
            )
            result = await session.execute(stmt_update)
            if result.rowcount == 0:
                # Row doesn't exist — insert
                insert_values: dict[str, Any] = {
                    "mini_id": self.mini_id,
                    "source_type": source_type,
                    "status": status,
                    "total_items": 0,
                    "explored_items": 0,
                    "findings_count": 0,
                    "memories_count": 0,
                    "quotes_count": 0,
                    "nodes_count": 0,
                }
                if status == "running":
                    insert_values["started_at"] = now
                stmt_insert = insert(ExplorerProgress).values(**insert_values)
                await session.execute(stmt_insert)
            await session.commit()

        try:
            if self.session_factory is not None:
                async with self.session_factory() as session:
                    await _do(session)
            else:
                await _do(self.db_session)
        except Exception as exc:
            logger.warning(
                "repo_agent: failed to upsert progress for %s/%s: %s",
                self.mini_id,
                source_type,
                exc,
            )
