"""Per-agent-role usage caps.

Background: PR #221 removed all artificial agent caps (`request_limit`,
`max_output_tokens=8192`) per the agency-first principle, after we discovered
the 8k cap was silently truncating chief aspect narratives mid-essay. But
removing all caps means a confused agent can loop forever — there is no
backstop short of the GitHub Actions / Fly machine timeout.

The middle ground: cap based on what each agent role actually needs. An
explorer iterating over 50 evidence items legitimately needs 100+ turns; an
aspect-narrative writer that finishes after a few reads + one essay does not.
A chat agent needs enough headroom for tool-use back-and-forth without
prematurely cutting off the user.

Each role specifies:
- `request_limit`     — total LLM calls before the agent loop is forced to
                        terminate. This is the backstop against runaway loops.
                        Set generously so it only fires on pathological cases,
                        not on legitimate work.
- `output_tokens_limit` — per-call output ceiling. None = let the model decide
                        (matches PR #221 intent for narrative-heavy roles).
- `total_tokens_limit` — overall input+output budget. None = no cap.

The `request_limit` here is the only knob that prevents infinite loops, so
every role MUST set it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentRole(str, Enum):
    """Identifies what an agent is being asked to do, for cap selection."""

    EXPLORER = "explorer"
    """Per-source evidence explorer. Iterates browse → read → save_finding/quote
    over the evidence DB. Naturally turn-heavy because it's one tool call per
    evidence item."""

    NARRATIVE_WRITER = "narrative_writer"
    """Aspect-narrative writer (chief fan-out). Reads a few evidence rows,
    writes one long essay, saves it. Few turns but high output tokens."""

    CHIEF_SYNTHESIZER = "chief_synthesizer"
    """Chief composer that assembles the soul document from already-written
    aspect narratives. Reads + composes; small number of turns."""

    REPO_AGENT = "repo_agent"
    """Per-repo agent that browses a local git clone. Iterates over files and
    git history; turn-heavy."""

    CHAT = "chat"
    """Interactive chat with a user. Needs headroom for multi-turn tool use
    without cutting off mid-conversation."""

    DEFAULT = "default"
    """Catch-all for callers that don't specify a role. Generous cap."""


@dataclass(frozen=True)
class AgentLimits:
    request_limit: int
    output_tokens_limit: int | None = None
    total_tokens_limit: int | None = None


# PydanticAI's `request_limit` counts every model HTTP call — both the
# tool-call request and the result-return request — so a single conceptual
# "turn" can consume 2+ requests. Caps below are sized at ~3-5× the highest
# legitimate observed turn count to leave headroom for retries and tool
# back-and-forth, while still bounding any pathological loop in finite time.
# Adjust as we learn from Langfuse traces.
ROLE_LIMITS: dict[AgentRole, AgentLimits] = {
    # Explorers iterate through ~50 evidence items per source, doing
    # browse→read→save_* loops. Observed peak ~120 turns. No output-token
    # cap — save_* tools take small structured arguments, not essays.
    AgentRole.EXPLORER: AgentLimits(request_limit=500),

    # Repo agents walk a local clone (tens of files × read_file/grep/git_show).
    # Observed peak ~80 turns.
    AgentRole.REPO_AGENT: AgentLimits(request_limit=400),

    # Aspect narrative writers do a handful of read calls then write one long
    # essay. ~5–15 turns is normal. NO output_tokens_limit — that was the v9
    # bug (truncated essays). Cap is the loop backstop, not a quality dial.
    AgentRole.NARRATIVE_WRITER: AgentLimits(request_limit=80),

    # Chief composer reads narrative essays + structured data and emits the
    # final soul prose. Even fewer turns than narrative writers.
    AgentRole.CHIEF_SYNTHESIZER: AgentLimits(request_limit=60),

    # Chat is interactive. Cap high so multi-step tool use isn't cut off, but
    # low enough that a runaway loop is bounded.
    AgentRole.CHAT: AgentLimits(request_limit=100),

    # Default: anything that didn't pass a role. Generous so we never break
    # an unidentified caller, but still finite.
    AgentRole.DEFAULT: AgentLimits(request_limit=150),
}


def limits_for(role: AgentRole | str | None) -> AgentLimits:
    """Look up the cap profile for a role; fall back to DEFAULT."""
    if role is None:
        return ROLE_LIMITS[AgentRole.DEFAULT]
    if isinstance(role, str):
        try:
            role = AgentRole(role)
        except ValueError:
            return ROLE_LIMITS[AgentRole.DEFAULT]
    return ROLE_LIMITS.get(role, ROLE_LIMITS[AgentRole.DEFAULT])
