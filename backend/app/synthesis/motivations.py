"""Goals & motivations extractor agent (ALLIE-429).

Reads ExplorerFinding + ExplorerQuote + Evidence rows for a mini and infers:
- short-term goals  (concrete near-term objectives)
- medium-term goals (6-24 month ambitions)
- terminal values   (deep motivational roots that persist over decades)
- anti-goals        (things they are actively trying to avoid)
- motivation chains (motivation → implied framework → observed behavior)

Returns a typed MotivationsProfile which gets persisted to Mini.motivations_json.
Never raises — the pipeline wrapper logs + skips on failure.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import ModelTier, get_model
from app.models.evidence import Evidence, ExplorerFinding, ExplorerQuote
from app.models.schemas import Motivation, MotivationChain, MotivationsProfile

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal structured output — LLM produces this; we map to schema contract
# ---------------------------------------------------------------------------


class _InferredMotivation(BaseModel):
    """LLM-inferred single motivation / goal / value."""

    value: str = Field(description="Short label, e.g. 'craftsmanship', 'autonomy'")
    category: Literal["short_term_goal", "medium_term_goal", "terminal_value", "anti_goal"] = Field(
        description="One of: short_term_goal, medium_term_goal, terminal_value, anti_goal"
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="2-3 Evidence or ExplorerFinding IDs that support this inference",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    reasoning: str = Field(description="One-sentence chain-of-thought")


class _InferredMotivationChain(BaseModel):
    """Causal chain: motivation → decision framework → observable behavior."""

    motivation: str = Field(description="Root motivation label, e.g. 'craftsmanship'")
    implied_framework: str = Field(
        description="Decision rule implied by the motivation, e.g. 'always write tests before merging'"
    )
    observed_behavior: str = Field(
        description="Concrete observable behavior, e.g. 'blocks PRs without tests'"
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="1-3 evidence IDs that show the behavior",
    )


class _MotivationsInferenceResult(BaseModel):
    """Full structured output from the motivations inference LLM call."""

    motivations: list[_InferredMotivation] = Field(
        description="All inferred motivations, goals, and values"
    )
    motivation_chains: list[_InferredMotivationChain] = Field(
        default_factory=list,
        description="Causal chains linking motivations to frameworks and behaviors",
    )
    summary: str = Field(
        description="2-3 sentence plain-language sketch of this person's motivational profile"
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert motivational analyst inferring a software developer's goals,
values, and decision-making drivers from their public behavioral evidence.

## Task
Given evidence from GitHub activity (commits, PRs, code reviews, issues),
blog posts, and other sources, infer the developer's motivational profile.

## Four motivation categories — use ALL of them

### short_term_goal
Concrete objectives the developer is actively working toward right now
(weeks to months).  Clues: recent project focus, current tickets, active
discussions, repeated patterns in recent commits.

### medium_term_goal
Ambitions with a 6-24 month horizon.  Clues: multi-stage project arcs,
skill investments (learning patterns), career hints, product roadmaps.

### terminal_value
Deep, stable motivational roots — things that drive ALL other goals.
These don't change.  Clues: consistent patterns across years of activity,
recurring themes in conflict/pushback, what they voluntarily spend
extra time on.  Examples: craftsmanship, autonomy, being trusted,
intellectual depth, impact, community stewardship.

### anti_goal
Things the developer is actively trying to avoid.  Clues: pushback moments,
explicit rejections, repeated complaints, behavioral boundaries.
Examples: looking incompetent, shipping regressions, being blocked,
corporate conformity, dependency lock-in.

## Methodology

For each inferred motivation:
1. Identify 2-3 pieces of evidence that support it.
2. Assign a confidence score (0.0-1.0).
   - ≥0.8: multiple independent evidence items strongly converge.
   - 0.5-0.79: clear pattern with some ambiguity.
   - <0.5: weak signal; only include if distinctive.
3. Write a one-sentence reasoning chain.

## Motivation chains
For each terminal_value or medium_term_goal, try to trace:
  motivation → implied decision framework → observable behavior

Example:
  motivation: "craftsmanship"
  implied_framework: "always write tests before merging"
  observed_behavior: "blocks PRs without adequate test coverage"

## Evidence citation rules
- ALWAYS cite 2-3 specific evidence_ids per motivation (from the provided rows).
- Use the "id" field from the provided findings/quotes/evidence rows.
- Prefer high-confidence ExplorerFinding rows over raw Evidence.
- If you have fewer than 5 distinct evidence items total, cap all
  confidence scores at 0.3 and set an honest summary.

Return a single JSON object conforming to the _MotivationsInferenceResult schema.
"""


def _build_user_prompt(
    username: str,
    findings: list[dict[str, Any]],
    quotes: list[dict[str, Any]],
    evidence_sample: list[dict[str, Any]],
) -> str:
    """Assemble evidence into a compact user prompt."""
    lines: list[str] = [f"## Developer: {username}", ""]

    if findings:
        lines.append(f"### ExplorerFindings ({len(findings)} rows)")
        for f in findings[:80]:
            lines.append(
                f"id={f['id']} [{f['category']} / {f['source_type']}] "
                f"conf={f['confidence']:.2f}: {f['content'][:300]}"
            )
        lines.append("")

    if quotes:
        lines.append(f"### ExplorerQuotes ({len(quotes)} rows)")
        for q in quotes[:40]:
            ctx = f" ({q['context']})" if q.get("context") else ""
            sig = f" [{q['significance']}]" if q.get("significance") else ""
            lines.append(f'id={q["id"]}{sig}: "{q["quote"][:200]}"{ctx}')
        lines.append("")

    if evidence_sample:
        lines.append(f"### Evidence sample ({len(evidence_sample)} rows, high-signal only)")
        for e in evidence_sample[:30]:
            lines.append(
                f"id={e['id']} [{e['item_type']} / {e['source_type']}]: {e['content'][:200]}"
            )
        lines.append("")

    lines.append(
        "Analyze the above evidence and return the _MotivationsInferenceResult JSON "
        "with inferred goals, values, anti-goals, and motivation chains."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def infer_motivations(
    mini_id: str,
    db_session: AsyncSession,
    username: str = "",
) -> MotivationsProfile:
    """Infer motivations profile from DB evidence for a mini.

    Reads ExplorerFinding + ExplorerQuote + Evidence rows, runs a structured
    inference call, and returns a validated MotivationsProfile.

    Args:
        mini_id: DB ID of the Mini record.
        db_session: Active async SQLAlchemy session.
        username: Optional display name for the prompt header.

    Returns:
        MotivationsProfile with motivations, chains, and summary.
        Returns a minimal empty profile on insufficient evidence.
    """
    # ── Load evidence from DB ─────────────────────────────────────────────
    findings_stmt = (
        select(ExplorerFinding)
        .where(ExplorerFinding.mini_id == mini_id)
        .order_by(ExplorerFinding.confidence.desc())
    )
    findings_rows = (await db_session.execute(findings_stmt)).scalars().all()

    quotes_stmt = select(ExplorerQuote).where(ExplorerQuote.mini_id == mini_id)
    quotes_rows = (await db_session.execute(quotes_stmt)).scalars().all()

    # High-signal evidence items
    evidence_stmt = (
        select(Evidence)
        .where(
            Evidence.mini_id == mini_id,
            Evidence.item_type.in_(
                [
                    "pr_review",
                    "review_comment",
                    "issue_comment",
                    "commit",
                    "blog_post",
                    "discussion_comment",
                    "stackoverflow_answer",
                ]
            ),
        )
        .order_by(Evidence.created_at.desc())
        .limit(50)
    )
    evidence_rows = (await db_session.execute(evidence_stmt)).scalars().all()

    findings = [
        {
            "id": f.id,
            "source_type": f.source_type,
            "category": f.category,
            "content": f.content,
            "confidence": f.confidence,
        }
        for f in findings_rows
    ]

    quotes = [
        {
            "id": q.id,
            "source_type": q.source_type,
            "quote": q.quote,
            "context": q.context,
            "significance": q.significance,
        }
        for q in quotes_rows
    ]

    evidence_sample = [
        {
            "id": e.id,
            "source_type": e.source_type,
            "item_type": e.item_type,
            "content": e.content,
        }
        for e in evidence_rows
    ]

    total_items = len(findings) + len(quotes) + len(evidence_sample)
    logger.info(
        "motivations mini_id=%s: %d findings, %d quotes, %d evidence items",
        mini_id,
        len(findings),
        len(quotes),
        len(evidence_sample),
    )

    if total_items == 0:
        logger.warning(
            "motivations mini_id=%s: no evidence found, returning empty profile",
            mini_id,
        )
        return MotivationsProfile(
            motivations=[],
            motivation_chains=[],
            summary="Insufficient evidence to infer motivations profile.",
        )

    # ── Build prompt ──────────────────────────────────────────────────────
    user_prompt = _build_user_prompt(username, findings, quotes, evidence_sample)
    model_name = get_model(ModelTier.STANDARD)

    # ── Run PydanticAI structured inference ───────────────────────────────
    agent: Agent[None, _MotivationsInferenceResult] = Agent(
        model=model_name,
        output_type=_MotivationsInferenceResult,
        system_prompt=_SYSTEM_PROMPT,
    )

    agent_result = await agent.run(user_prompt)
    raw: _MotivationsInferenceResult = agent_result.output

    logger.info(
        "motivations mini_id=%s: inferred %d motivations, %d chains",
        mini_id,
        len(raw.motivations),
        len(raw.motivation_chains),
    )

    # ── Map to schema contract ────────────────────────────────────────────
    motivations = [
        Motivation(
            value=m.value,
            category=m.category,
            evidence_ids=m.evidence_ids,
            confidence=m.confidence,
        )
        for m in raw.motivations
    ]

    chains = [
        MotivationChain(
            motivation=c.motivation,
            implied_framework=c.implied_framework,
            observed_behavior=c.observed_behavior,
            evidence_ids=c.evidence_ids,
        )
        for c in raw.motivation_chains
    ]

    return MotivationsProfile(
        motivations=motivations,
        motivation_chains=chains,
        summary=raw.summary,
    )


# ---------------------------------------------------------------------------
# System-prompt helper
# ---------------------------------------------------------------------------


def build_motivations_block(profile: MotivationsProfile) -> str:
    """Render a MotivationsProfile into a MOTIVATIONS prompt block.

    Designed to be embedded in the system prompt produced by
    `spirit.build_system_prompt()`.
    """
    if not profile or not profile.motivations:
        return ""

    lines: list[str] = ["## MOTIVATIONS (inferred from evidence)"]

    # Group by category
    by_cat: dict[str, list[Motivation]] = {}
    for m in profile.motivations:
        by_cat.setdefault(m.category, []).append(m)

    cat_labels = {
        "short_term_goal": "Short-term",
        "medium_term_goal": "Medium-term",
        "terminal_value": "Terminal values",
        "anti_goal": "Anti-goals",
    }

    for cat_key in ["short_term_goal", "medium_term_goal", "terminal_value", "anti_goal"]:
        items = by_cat.get(cat_key, [])
        if not items:
            continue
        label = cat_labels[cat_key]
        values_str = ", ".join(m.value for m in items)
        lines.append(f"- {label}: {values_str}")

    if profile.motivation_chains:
        lines.append("\nMotivation chains:")
        for chain in profile.motivation_chains[:6]:  # cap to keep token budget reasonable
            lines.append(
                f'- {chain.motivation} → "{chain.implied_framework}" → {chain.observed_behavior}'
            )

    return "\n".join(lines)
