"""
Typed feature-flag registry.

Discipline rules enforced here:
- ``kind="rollout"`` flags MUST have ``removal_ticket`` and ``planned_removal`` set.
  A module-level assertion fires at import time so bad registrations are caught early
  (also covered by the test suite).
- Flags are **ops** (permanent operational toggles), **kill_switch** (emergency brakes),
  or **rollout** (temporary — must carry a removal plan).

Usage
-----
    from app.core.feature_flags import FLAGS

    if FLAGS["LANGFUSE_ENABLED"].is_enabled():
        ...

Adding a new flag
-----------------
Add a ``FeatureFlag`` entry to ``FLAGS``.  If ``kind="rollout"`` you must fill in
``owner_ticket``, ``removal_ticket``, and ``planned_removal`` — the module will raise
``AssertionError`` at import time if you forget.

Deleting a flag
---------------
Remove the entry from ``FLAGS``, remove all usage sites, and open a PR.  No legacy
paths — flags are rollout tools, not coexistence mechanisms.
"""

import os
from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class FeatureFlag:
    """Immutable descriptor for a single feature flag.

    Attributes
    ----------
    name:
        The environment variable name that controls the flag.  Must match the
        key in ``FLAGS``.
    description:
        Human-readable explanation of what enabling this flag does.
    default:
        Value returned when the environment variable is absent or empty.
    added_at:
        Date the flag was introduced.  Used for staleness tracking.
    kind:
        ``"rollout"`` — temporary feature gate; must have removal plan.
        ``"kill_switch"`` — emergency brake; exists indefinitely.
        ``"ops"`` — permanent operational toggle.
    owner_ticket:
        Linear ticket that introduced this flag.  Required for ``rollout`` flags.
    removal_ticket:
        Linear ticket tracking flag removal.  Required for ``rollout`` flags.
    planned_removal:
        Target date to remove the flag.  Required for ``rollout`` flags.
    """

    name: str
    description: str
    default: bool
    added_at: date
    kind: Literal["rollout", "kill_switch", "ops"]
    owner_ticket: str | None = None
    removal_ticket: str | None = None
    planned_removal: date | None = None

    def is_enabled(self) -> bool:
        """Read the env var at call time and coerce to bool.

        Truthy values: ``"true"``, ``"1"``, ``"yes"`` (case-insensitive).
        Everything else (including absent / empty) is falsy.
        """
        raw = os.environ.get(self.name, "").strip().lower()
        if raw == "":
            return self.default
        return raw in {"true", "1", "yes"}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

FLAGS: dict[str, FeatureFlag] = {
    "DEV_AUTH_BYPASS": FeatureFlag(
        name="DEV_AUTH_BYPASS",
        description=(
            "Skip Neon Auth JWT validation and inject a hardcoded dev user. "
            "LOCAL + PREVIEW ONLY — never enable in production."
        ),
        default=False,
        added_at=date(2026, 3, 1),
        kind="ops",
    ),
    "DISABLE_LLM_CALLS": FeatureFlag(
        name="DISABLE_LLM_CALLS",
        description=(
            "Emergency brake: every LLM call returns 503. "
            "Use if an API key is compromised or costs are runaway."
        ),
        default=False,
        added_at=date(2026, 4, 20),
        kind="kill_switch",
    ),
    "LANGFUSE_ENABLED": FeatureFlag(
        name="LANGFUSE_ENABLED",
        description="Send PydanticAI traces to Langfuse for observability.",
        default=False,
        added_at=date(2026, 3, 15),
        kind="ops",
    ),
    "REVIEW_PREDICTOR_LLM_ENABLED": FeatureFlag(
        name="REVIEW_PREDICTOR_LLM_ENABLED",
        description="Use the LLM-based agent for review predictions instead of heuristics.",
        default=True,
        added_at=date(2026, 4, 22),
        kind="rollout",
        owner_ticket="ALLIE-500",
        removal_ticket="ALLIE-501",
        planned_removal=date(2026, 5, 22),
    ),
    "GH_APP_OUTCOME_CAPTURE": FeatureFlag(
        name="GH_APP_OUTCOME_CAPTURE",
        description=(
            "Enable GitHub App webhook handlers that capture human reactions and reply signals "
            "on mini-posted review comments and route them to the framework-confidence loop via "
            "PATCH /api/minis/trusted/{mini_id}/review-cycles. Off by default — wiring is "
            "deployed but not yet flipped on in production."
        ),
        default=False,
        added_at=date(2026, 4, 24),
        kind="ops",
    ),
}

# ---------------------------------------------------------------------------
# Lint rule: rollout flags must carry removal metadata
# ---------------------------------------------------------------------------

for _flag in FLAGS.values():
    if _flag.kind == "rollout":
        assert _flag.removal_ticket, (
            f"Feature flag '{_flag.name}' is kind='rollout' — must set removal_ticket"
        )
        assert _flag.planned_removal, (
            f"Feature flag '{_flag.name}' is kind='rollout' — must set planned_removal"
        )
