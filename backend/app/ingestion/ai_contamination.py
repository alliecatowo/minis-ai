"""Author-grounded LLM AI-contamination classifier (ALLIE-445).

Detects whether a piece of evidence text is consistent with how a specific
author writes (authentic) or reads as AI-generated surrogate voice.

The key insight: we're NOT running a generic AI detector.  We're asking
"does this text sound like *this person*?" — which requires an author
baseline for comparison.

Does NOT wire into the pipeline here; that's ALLIE-447.
Does NOT backfill existing evidence; that's ALLIE-443.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from app.core.compaction import create_compaction_processor
from app.core.models import ModelTier, get_model

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class AIDetectionResult(BaseModel):
    """Structured result from the author-grounded AI-contamination classifier."""

    score: float = Field(
        ge=0.0,
        le=1.0,
        description="0.0 = authentic author voice, 1.0 = AI-generated surrogate voice",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Classifier confidence in the score (0.0 = very uncertain, 1.0 = certain)",
    )
    reasoning: str = Field(
        description="One-sentence explanation of the key signal that drove the score",
    )


class AuthorBaseline(BaseModel):
    """Known-authentic text samples from the author, used as a reference baseline."""

    username: str = Field(description="GitHub username / author identifier")
    samples: list[str] = Field(
        description="2-3 known-authentic text samples from the same author",
    )
    source_hint: str | None = Field(
        default=None,
        description="Where the samples come from, e.g. 'github commit messages', 'blog posts'",
    )


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You evaluate whether a piece of developer text is consistent with how a specific
author writes, or whether it is AI-generated surrogate voice.

You are given 2-3 authentic samples from the author as a baseline.
Your job is NOT to detect AI in the abstract — it is to detect voice mismatch
against this specific author's established writing style.

Consider:
- Sentence-length burstiness (humans vary; AI is uniform)
- Vocabulary fit (author's usual register and word choices)
- Technical register and specificity
- Structural patterns (AI often uses numbered lists, polished openers, closing boilerplate)
- Personal tics, typos, informal grammar present in baseline but absent in candidate

Return score 0.0 if the candidate matches the author's voice well.
Return score 1.0 if the candidate reads as clearly AI-generated surrogate voice.
Return confidence 0.0–1.0 for how certain you are.
Keep reasoning to one sentence focusing on the most decisive signal.
"""


def _build_user_prompt(text: str, baseline: AuthorBaseline) -> str:
    """Build the user-facing prompt for the classifier."""
    source_label = baseline.source_hint or "author samples"
    samples_block = "\n\n".join(
        f"[Sample {i + 1}]\n{s}" for i, s in enumerate(baseline.samples)
    )
    return (
        f"Author: {baseline.username}\n"
        f"Baseline ({source_label}):\n\n"
        f"{samples_block}\n\n"
        f"---\n\n"
        f"Candidate text:\n{text}\n\n"
        f"Compare: is the candidate consistent with this author's voice, "
        f"or AI-generated? Output score (0=authentic, 1=AI), confidence, "
        f"and one-sentence reasoning."
    )


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


async def score_ai_contamination(
    text: str,
    baseline: AuthorBaseline,
    model: str | None = None,
) -> AIDetectionResult:
    """Author-grounded LLM-based AI-contamination classifier.

    Compares candidate text against known-authentic baseline samples from the
    same author. Returns a structured result with score, confidence, and
    reasoning.

    ALLIE-405 cost caps apply: uses STANDARD tier (Gemini Flash / Claude Sonnet
    / GPT-4.1 depending on DEFAULT_PROVIDER). One LLM call per evaluation.
    No streaming, no tools.

    Args:
        text: The candidate text to evaluate.
        baseline: Author baseline with 2-3 authentic samples.
        model: Optional model override (PydanticAI model string). Defaults to
               STANDARD tier for the active provider.

    Returns:
        AIDetectionResult with score, confidence, and reasoning.

    Raises:
        Exception propagated from PydanticAI on hard failures. Callers that
        want failure-safe behaviour should wrap in try/except.
    """
    resolved_model = model or get_model(ModelTier.STANDARD)
    user_prompt = _build_user_prompt(text, baseline)

    processor = create_compaction_processor(resolved_model)
    history_processors = [processor] if processor else None

    agent: Agent[None, AIDetectionResult] = Agent(
        resolved_model,
        instructions=_SYSTEM_PROMPT,
        output_type=AIDetectionResult,
        history_processors=history_processors,
    )

    result = await agent.run(user_prompt)
    return result.output
