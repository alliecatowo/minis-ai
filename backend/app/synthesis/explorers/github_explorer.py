"""GitHub explorer — analyzes GitHub activity to extract personality signals.

Code reviews, PR descriptions, commit messages, and issue discussions are
the richest source of developer personality data. This explorer is tuned to
find the human behind the code: how they argue, what they defend, what makes
them excited, and how they phrase objections.

The explorer also has tools to browse actual source code in repos, letting it
investigate project structure, coding style, and technical choices directly.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import PurePosixPath

import httpx

from app.core.agent import AgentTool
from app.core.config import settings
from app.ingestion.github_http import gh_request
from app.synthesis.explorers.base import Explorer, ExplorerReport

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"

# Directories to skip when browsing repos
_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "vendor",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",
        "out",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "coverage",
        ".gradle",
        ".idea",
        ".vscode",
        ".settings",
        "bin",
        "obj",
    }
)

# File extensions to skip (binary/generated)
_SKIP_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".bmp",
        ".svg",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".bin",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".o",
        ".a",
        ".pyc",
        ".pyo",
        ".class",
        ".jar",
        ".min.js",
        ".min.css",
        ".map",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".mp3",
        ".mp4",
        ".wav",
        ".avi",
        ".mov",
    }
)

# Lock files to skip
_SKIP_FILES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "poetry.lock",
        "Gemfile.lock",
        "composer.lock",
        "go.sum",
        ".DS_Store",
        "Thumbs.db",
    }
)

# Max file size to read (bytes) — skip huge generated files
_MAX_FILE_SIZE = 25_000


def _should_skip_file(name: str) -> bool:
    """Check if a file should be skipped based on name/extension."""
    if name in _SKIP_FILES:
        return True
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in _SKIP_EXTENSIONS:
        return True
    if name.endswith(".min.js") or name.endswith(".min.css"):
        return True
    return False


def _should_skip_dir(name: str) -> bool:
    """Check if a directory should be skipped."""
    return name.lower() in _SKIP_DIRS or name.startswith(".")


def _gh_headers() -> dict[str, str]:
    """Build GitHub API headers."""
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


class GitHubExplorer(Explorer):
    """Explorer specialized for GitHub code collaboration artifacts."""

    source_name = "github"

    def system_prompt(self) -> str:
        return _SYSTEM_PROMPT

    def user_prompt(self, username: str, evidence: str, raw_data: dict) -> str:
        return (
            f"Analyze github evidence for {username}. "
            "Use tools to browse, read, and extract. Thoroughness matters."
        )

    async def explore(self, username: str, evidence: str, raw_data: dict) -> ExplorerReport:
        """Override to add repo browsing tools for deeper investigation.

        A single pooled ``httpx.AsyncClient`` is shared by all three tools for
        the duration of the explorer run. A per-instance ``asyncio.Semaphore``
        caps concurrent GitHub API calls to 2 so we don't blow through the
        rate limit even if the agent fans out tool calls in parallel.
        """
        repos_summary = raw_data.get("repos_summary", {})
        all_repos = repos_summary.get("top_repos", [])
        repo_fullnames = {
            r.get("name", ""): r.get("full_name", f"{username}/{r.get('name', '')}")
            for r in all_repos
        }

        # Lazy-init the semaphore inside the running event loop (event-loop safety).
        self._gh_semaphore = asyncio.Semaphore(2)

        def _resolve_repo(repo_name: str) -> str:
            """Resolve short repo name to full_name."""
            return repo_fullnames.get(repo_name, f"{username}/{repo_name}")

        async with httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
        ) as client:

            async def lookup_repo(repo_name: str) -> str:
                """Fetch README, file listing, and recent commits for a repo."""
                full_name = _resolve_repo(repo_name)
                headers = _gh_headers()
                parts: list[str] = [f"## Repo overview: {full_name}"]

                async with self._gh_semaphore:
                    try:
                        resp = await gh_request(
                            client,
                            "GET",
                            f"{_GH_API}/repos/{full_name}/readme",
                            headers=headers,
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            content = data.get("content", "")
                            if content:
                                readme_text = base64.b64decode(content).decode(
                                    "utf-8", errors="replace"
                                )
                                if len(readme_text) > 3000:
                                    readme_text = readme_text[:3000] + "\n... (truncated)"
                                parts.append(f"### README\n{readme_text}")
                        else:
                            parts.append("No README found.")
                    except Exception:
                        parts.append("Failed to fetch README.")

                    try:
                        resp = await gh_request(
                            client,
                            "GET",
                            f"{_GH_API}/repos/{full_name}/contents",
                            headers=headers,
                        )
                        if resp.status_code == 200:
                            items = resp.json()
                            if isinstance(items, list):
                                file_lines = []
                                for item in items[:50]:
                                    kind = item.get("type", "file")
                                    name = item.get("name", "?")
                                    size = item.get("size", 0)
                                    if kind == "dir":
                                        skip = " (skipped)" if _should_skip_dir(name) else ""
                                        file_lines.append(f"  [dir] {name}/{skip}")
                                    else:
                                        size_str = f" ({size}B)" if size else ""
                                        file_lines.append(f"  [file] {name}{size_str}")
                                parts.append("### File structure\n" + "\n".join(file_lines))
                    except Exception:
                        parts.append("Failed to fetch file listing.")

                    try:
                        resp = await gh_request(
                            client,
                            "GET",
                            f"{_GH_API}/repos/{full_name}/commits",
                            headers=headers,
                            params={"per_page": "10"},
                        )
                        if resp.status_code == 200:
                            commits = resp.json()
                            if isinstance(commits, list) and commits:
                                commit_lines = []
                                for c in commits[:10]:
                                    msg = c.get("commit", {}).get("message", "").split("\n")[0]
                                    commit_lines.append(f"  - {msg}")
                                parts.append("### Recent commits\n" + "\n".join(commit_lines))
                    except Exception:
                        pass

                return "\n\n".join(parts)

            async def browse_repo(repo_name: str, path: str = "") -> str:
                """Browse a directory in a repo, showing files and subdirectories."""
                full_name = _resolve_repo(repo_name)
                headers = _gh_headers()
                api_path = (
                    f"{_GH_API}/repos/{full_name}/contents/{path}"
                    if path
                    else f"{_GH_API}/repos/{full_name}/contents"
                )

                async with self._gh_semaphore:
                    try:
                        resp = await gh_request(client, "GET", api_path, headers=headers)
                        if resp.status_code == 404:
                            return f"Path not found: {path or '/'}"
                        if resp.status_code != 200:
                            return f"Error fetching {path or '/'}: HTTP {resp.status_code}"

                        items = resp.json()
                        if not isinstance(items, list):
                            return f"Path '{path}' is a file, not a directory. Use read_file to read it."

                        lines = [f"## Contents of {full_name}/{path or ''}"]
                        dirs = []
                        files = []

                        for item in items:
                            kind = item.get("type", "file")
                            name = item.get("name", "?")
                            size = item.get("size", 0)

                            if kind == "dir":
                                if _should_skip_dir(name):
                                    dirs.append(f"  [dir] {name}/ (skipped \u2014 generated/deps)")
                                else:
                                    dirs.append(f"  [dir] {name}/")
                            else:
                                skip = _should_skip_file(name)
                                size_str = f" ({size:,}B)" if size else ""
                                skip_str = " (binary/generated \u2014 skipped)" if skip else ""
                                files.append(f"  [file] {name}{size_str}{skip_str}")

                        if dirs:
                            lines.append("### Directories")
                            lines.extend(sorted(dirs))
                        if files:
                            lines.append("### Files")
                            lines.extend(sorted(files))

                        return "\n".join(lines)

                    except Exception as e:
                        return f"Failed to browse {path or '/'}: {e}"

            async def read_file(repo_name: str, path: str) -> str:
                """Read the raw content of a source code file from a repo."""
                full_name = _resolve_repo(repo_name)
                headers = _gh_headers()
                filename = PurePosixPath(path).name

                if _should_skip_file(filename):
                    return f"Skipped '{path}' \u2014 binary or generated file."

                async with self._gh_semaphore:
                    try:
                        resp = await gh_request(
                            client,
                            "GET",
                            f"{_GH_API}/repos/{full_name}/contents/{path}",
                            headers=headers,
                        )
                        if resp.status_code == 404:
                            return f"File not found: {path}"
                        if resp.status_code != 200:
                            return f"Error fetching {path}: HTTP {resp.status_code}"

                        data = resp.json()

                        if isinstance(data, list):
                            return f"'{path}' is a directory. Use browse_repo instead."

                        size = data.get("size", 0)
                        if size > _MAX_FILE_SIZE:
                            return (
                                f"File '{path}' is {size:,} bytes \u2014 too large to read. "
                                f"Max is {_MAX_FILE_SIZE:,} bytes."
                            )

                        content = data.get("content", "")
                        encoding = data.get("encoding", "")

                        if encoding == "base64" and content:
                            text = base64.b64decode(content).decode("utf-8", errors="replace")
                        elif content:
                            text = content
                        else:
                            return f"File '{path}' is empty or has no content."

                        return f"## {full_name}/{path}\n\n```\n{text}\n```"

                    except Exception as e:
                        return f"Failed to read {path}: {e}"

            # Inject the extra tools into the base explore() flow
            self._extra_tools = [
                AgentTool(
                    name="lookup_repo",
                    description=(
                        "Get a quick overview of a repository: README, top-level file "
                        "structure, and recent commits. Use this first to get the lay of "
                        "the land before diving into specific files."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "repo_name": {
                                "type": "string",
                                "description": "Short name of the repository (e.g., 'keyboard-firmware')",
                            },
                        },
                        "required": ["repo_name"],
                    },
                    handler=lookup_repo,
                ),
                AgentTool(
                    name="browse_repo",
                    description=(
                        "List files and directories at a specific path in a repository. "
                        "Use this to navigate into subdirectories and find interesting "
                        "source code files. Skips binary/generated files automatically."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "repo_name": {
                                "type": "string",
                                "description": "Short name of the repository",
                            },
                            "path": {
                                "type": "string",
                                "description": "Path within the repo (e.g., 'src/lib' or '' for root). Defaults to root.",
                            },
                        },
                        "required": ["repo_name"],
                    },
                    handler=browse_repo,
                ),
                AgentTool(
                    name="read_file",
                    description=(
                        "Read the raw source code of a file from a repository. Use this "
                        "to examine actual code, config files, Makefiles, etc. to understand "
                        "the developer's coding style, technical choices, and project architecture. "
                        "Automatically skips binary/generated files and enforces size limits."
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "repo_name": {
                                "type": "string",
                                "description": "Short name of the repository",
                            },
                            "path": {
                                "type": "string",
                                "description": "Full path to the file within the repo (e.g., 'src/main.c', 'Makefile')",
                            },
                        },
                        "required": ["repo_name", "path"],
                    },
                    handler=read_file,
                ),
            ]

            return await super().explore(username, evidence, raw_data)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a Voice Forensics Investigator. Your mission is to reverse-engineer the \
mental and verbal operating system of a developer from their digital exhaust. \
You are NOT writing a biography. You are building a dataset to train a neural \
clone.

Your goal is High-Fidelity Pattern Recognition. You must capture the specific \
texture of how this person thinks, types, and codes.

## AUTONOMOUS EVIDENCE EXPLORATION

You operate autonomously. Evidence is stored in a database, NOT injected into \
your prompt. You MUST use your tools to discover and read evidence:

1. **browse_evidence(source_type="github")** — paginate through available evidence \
items (PRs, review comments, issue comments, commits). Start here to survey scope.
2. **read_item(item_id)** — read the full content of a specific evidence item. \
Use this to dive deep into interesting items.
3. **search_evidence(query)** — keyword search across evidence content. Use to \
find specific patterns (e.g., "refactor", "TODO", "disagree").
4. **mark_explored(item_id)** — mark an item as analyzed so you track coverage.
5. **get_progress()** — check how many items you have explored, findings saved, etc.

After reading and analyzing evidence, persist your findings:
- **save_finding** — personality/behavioral insights
- **save_memory** — factual knowledge about the developer
- **save_quote** — exact quotes that reveal voice and character
- **save_knowledge_node** / **save_knowledge_edge** — build the knowledge graph
- **save_principle** — decision rules and values

When done, call **finish(summary)** with a summary of what you found.

**SMART FILTERING:** Skip lock files (package-lock.json, yarn.lock, etc.), \
auto-generated content, and binary artifacts. Focus on human-written content: \
PR descriptions, review comments, issue discussions, commit messages, READMEs, \
and source code.

## THE INVESTIGATION PROTOCOL: The Abductive Loop

Do not just "scan" repos. You are a detective. For every observation, run this loop:

1.  **OBSERVE:** "They used a 300-line function in `utils.py` but preach clean code in `README.md`."
2.  **HYPOTHESIZE:**
    *   *H1:* They are a "Pragmatic Hypocrite" (Speed > Rules).
    *   *H2:* `utils.py` is legacy code they didn't write.
3.  **VERIFY:** Check commit history or other evidence. If they wrote it recently, H1 is confirmed.

## PRIORITY 1: STYLOMETRIC MIRRORING (The "How")

Capture the MICRO-PATTERNS of their communication. Don't just say "casual". \
Extract the **Style Spec**:

*   **Sentence Entropy:** Do they write in staccato bursts? Or long, flowing paragraphs?
*   **Punctuation Density:** specific frequency of em-dashes, semicolons, ellipses. \
    "Uses '...' to trail off 3 times per thread."
*   **Connective Tissue:** How do they transition? ("So...", "Anyway...", "However,").
*   **Lexical Temperature:** Do they use "esoteric" words (e.g., "orthogonal") or \
    "plain" words (e.g., "weird")?
*   **Typing Mechanics:**
    *   Capitalization (all lowercase? Title Case? Random?)
    *   Emoji usage (Irony vs. sincerity? Specific skin tones?)

## PRIORITY 2: THE HIERARCHY OF EVIDENCE

Not all evidence is equal.
1.  **TIER 1 (Behavior):** Source code, Commit messages. This is what they DO. \
    *Truth Level: High.*
2.  **TIER 2 (Speech):** PR descriptions, READMEs. This is what they SAY they do. \
    *Truth Level: Medium.*
3.  **TIER 3 (Projection):** Bio, Website about page. This is what they WANT to be. \
    *Truth Level: Low (Aspirational).*

**CRITICAL:** When Tier 1 conflicts with Tier 2, the CONFLICT is the personality feature. \
(e.g., "Claims to love testing (Tier 2) but has 0% coverage (Tier 1)" -> \
Feature: "Aspirational Tester / Guilt-driven").

## PRIORITY 3: THE BRAIN (The Knowledge Graph)

You are building a **connected Knowledge Graph**, not a flat list. A Node without \
Edges is dead data.

*   **Connectivity Rule:** For every technology/concept you identify, you must link it.
    *   *Bad:* Saving `Node("React")`.
    *   *Good:* Saving `Node("React")` AND `Edge("React", "my-frontend-repo", "USED_IN")`.
    *   *Best:* `Edge("React", "Component Composition", "EXPERT_IN")` (if they use advanced patterns).

*   **Code Pattern Fingerprinting:**
    *   *Functional vs OO:* Do they write pure functions or complex class hierarchies?
    *   *Error Handling:* Do they let it crash? Use `Result` types? Wrap everything in try/catch?
    *   *Testing Philosophy:* Do they write unit tests (mockist) or integration tests?

*   **Dependency Forensics:**
    *   Uses `zod`? -> **Value:** Runtime safety.
    *   Uses `lodash` in 2024? -> **Pattern:** Legacy habits / Pragmatic.
    *   Uses `htmx`? -> **Philosophy:** Anti-SPA / Hypermedia-driven.

## PRIORITY 4: THE SOUL (Values & Decision Logic)

Capture the **Decision Boundaries** of the persona and **Link them to Code**.

*   **The "No" Filter:** What do they REJECT in PRs?
*   **The "Hill to Die On":** What opinions do they defend aggressively?
*   **The "Anti-Patterns":** What coding styles trigger a rant?

## PRIORITY 5: THE NEGATIVE SPACE (The Shadow)

Define the persona by what it is NOT.
*   **Banned Tokens:** What words do they NEVER use?
*   **Emotional Floor/Ceiling:** Do they NEVER get excited? Do they NEVER apologize?
*   **The "Anti-Helper":** Unlike ChatGPT, real devs are often terse, dismissive, or \
    expect you to RTFM. Capture this.

## EXECUTION GUIDELINES

### Exhaustiveness IS Quality
- Start with browse_evidence to survey ALL available evidence items.
- Page through ALL items using browse_evidence with increasing page numbers.
- Read the most interesting items in full with read_item.
- Use search_evidence to find specific patterns across all evidence.
- For top repos: use lookup_repo then browse source code with browse_repo and read_file.
- Save findings AS YOU READ, not all at the end.
- Mark items as explored with mark_explored as you go.
- Check get_progress periodically to ensure thorough coverage.
- You have 50 turns. Use them ALL. Do not finish early.

### The "Ghost-Writer" Standard
You are done when you can answer this: "If I had to ghost-write a rejection \
comment for a junior dev's PR as this person, exactly what words, tone, and \
punctuation would I use?"

## TERMINATION CONDITIONS

Do not stop just because you hit a number. Stop when you have:
1.  **The Style Spec:** detailed enough to simulate their typing.
2.  **The Boundary Map:** clear understanding of what they love vs. hate.
3.  **The Context Matrix:** how they shift tone between code (formal?) and \
issues (casual?).

Call **finish()** only when genuinely done with thorough analysis.
"""


# --- Registration ---

from app.synthesis.explorers import register_explorer  # noqa: E402

register_explorer("github", GitHubExplorer)
