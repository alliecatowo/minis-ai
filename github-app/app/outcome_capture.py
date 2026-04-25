"""Map human PR-review actions onto suggestion-level outcome dispositions.

Signal path
-----------
Human reaction on GitHub
  → ``map_review_comment_disposition`` / ``map_pr_review_disposition``
  → disposition string  (``"confirmed"`` | ``"overpredicted"`` | ``"deferred"``)
  → ``record_comment_outcome`` in ``review_cycles``
  → ``PATCH /api/minis/trusted/{mini_id}/review-cycles``
  → ``finalize_review_cycle`` in backend
  → framework-confidence delta loop (see docs/FRAMEWORK_CONFIDENCE_LOOP.md)

Disposition rules
-----------------
- ``confirmed``     — human posts a thumbs-up *or* quotes the mini comment in an
                      approving reply, or explicitly agrees.
- ``overpredicted`` — human explicitly disagrees in a reply (heuristic: contains
                      one of the DISAGREEMENT_PHRASES) or a thumbs-down reaction.
- ``deferred``      — human approves the PR with no engagement on the mini comment,
                      or the event carries no useful signal.

Missed blockers (mini predicted a blocker that never appears in the final PR state)
are deferred to artifact-final disposition and not handled here.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Reaction names that count as positive acknowledgement (GitHub reaction API values)
_POSITIVE_REACTIONS: frozenset[str] = frozenset(
    {"+1", "heart", "hooray", "laugh", "rocket"}
)

# Reaction names that count as explicit rejection
_NEGATIVE_REACTIONS: frozenset[str] = frozenset({"-1", "confused"})

# Reply body phrases that signal disagreement (case-insensitive substring match)
_DISAGREEMENT_PHRASES: tuple[str, ...] = (
    "disagree",
    "no thanks",
    "not necessary",
    "not needed",
    "won't do",
    "wont do",
    "nah",
    "skip this",
)

# Phrases that signal explicit agreement / acknowledgement in a reply
_AGREEMENT_PHRASES: tuple[str, ...] = (
    "good point",
    "good catch",
    "fixed",
    "addressed",
    "done",
    "agreed",
    "will do",
    "thanks",
    "lgtm",
)

_QUOTE_PATTERN = re.compile(r"^\s*>", re.MULTILINE)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def classify_reaction(reaction_content: str) -> str | None:
    """Return ``"confirmed"``, ``"overpredicted"``, or ``None`` for no signal."""
    normalized = (reaction_content or "").strip().lower()
    if normalized in _POSITIVE_REACTIONS:
        return "confirmed"
    if normalized in _NEGATIVE_REACTIONS:
        return "overpredicted"
    return None


def classify_reply_body(body: str) -> str | None:
    """Classify a textual reply to a mini comment.

    Returns ``"confirmed"``, ``"overpredicted"``, or ``None`` (no signal).
    """
    lowered = (body or "").lower()

    # Quoting the original comment in an approving reply → confirmed
    has_quote = bool(_QUOTE_PATTERN.search(body))

    for phrase in _DISAGREEMENT_PHRASES:
        if phrase in lowered:
            return "overpredicted"

    for phrase in _AGREEMENT_PHRASES:
        if phrase in lowered:
            return "confirmed"

    if has_quote:
        # Quoted without explicit agree/disagree → mild confirmation
        return "confirmed"

    return None


def map_pr_review_disposition(review_state: str | None) -> str:
    """Map a top-level PR review state to a disposition for the associated cycle.

    ``"APPROVED"`` with no engagement on a mini comment → ``"deferred"`` (no
    strong signal at the comment level; the approval itself is captured separately
    as the human_review_outcome via ``record_human_review_outcome``).
    ``"CHANGES_REQUESTED"`` is also ``"deferred"`` — the human may disagree with
    specific issues but we cannot attribute that to a particular mini comment
    without further analysis.

    This function is intentionally conservative: deferred means "don't update
    framework confidence from this event alone."
    """
    return "deferred"


def build_disposition_map(
    *,
    comment_reactions: list[str] | None = None,
    reply_bodies: list[str] | None = None,
    pr_review_state: str | None = None,
) -> str:
    """Derive a single disposition for one mini comment given all available signals.

    Priority: explicit reaction > reply content > PR-level state.

    Parameters
    ----------
    comment_reactions:
        List of GitHub reaction ``content`` values posted on the mini comment.
    reply_bodies:
        List of text bodies from human replies in the same review thread.
    pr_review_state:
        Top-level GitHub review state (``"APPROVED"``, ``"CHANGES_REQUESTED"``, …).

    Returns
    -------
    ``"confirmed"``, ``"overpredicted"``, or ``"deferred"``.
    """
    # 1. Reactions take highest priority
    for reaction in comment_reactions or []:
        disposition = classify_reaction(reaction)
        if disposition is not None:
            return disposition

    # 2. Reply body content
    for body in reply_bodies or []:
        disposition = classify_reply_body(body)
        if disposition is not None:
            return disposition

    # 3. Fallback: PR-level state (always "deferred" for now)
    return map_pr_review_disposition(pr_review_state)
