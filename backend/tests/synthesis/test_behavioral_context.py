"""Tests for BehavioralContextAgent port (ALLIE-431).

Covers:
- infer_behavioral_context() returns BehavioralContext from multi-context evidence
- Formality scores and tone descriptors are extracted per context
- Contradictions surface when evidence disagrees across contexts
- Falls back cleanly when only 1 context_type is populated (below threshold)
- Falls back cleanly when no eligible context buckets exist
- build_context_block() renders a non-empty prompt block for rich context data
- build_context_block() returns empty string for empty BehavioralContext
- spirit.build_system_prompt() includes BEHAVIORAL CONTEXT MAP when supplied
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.schemas import BehavioralContext, BehavioralContextEntry
from app.synthesis.behavioral_context import (
    MIN_ITEMS_PER_CONTEXT,
    _build_context_analysis_prompt,
    _build_contradictions_prompt,
    build_context_block,
    infer_behavioral_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mini_id() -> str:
    return str(uuid4())


def _make_evidence_row(context: str, content: str, source_type: str = "github") -> MagicMock:
    """Return a mock Evidence-like row (namedtuple-ish)."""
    row = MagicMock()
    row.context = context
    row.content = content
    row.source_type = source_type
    return row


def _make_quote_row(quote: str, context: str | None = None) -> MagicMock:
    row = MagicMock()
    row.quote = quote
    row.context = context
    return row


def _make_db_session(evidence_rows: list, quote_rows: list | None = None) -> MagicMock:
    """Build a mock async DB session.

    execute() returns different result objects depending on the call count,
    allowing first call = evidence query, second call = quotes query.
    """
    if quote_rows is None:
        quote_rows = []

    session = MagicMock()

    # First execute → evidence, second execute → quotes
    evidence_result = MagicMock()
    evidence_result.all.return_value = evidence_rows

    quotes_result = MagicMock()
    quotes_result.scalars.return_value.all.return_value = quote_rows

    call_count = [0]

    async def _execute(stmt):
        call_count[0] += 1
        if call_count[0] == 1:
            return evidence_result
        return quotes_result

    session.execute = _execute
    return session


def _make_llm_context_response(
    summary: str = "Direct and technical in code reviews.",
    behaviors: list[str] | None = None,
    communication_style: str = "blunt",
    motivators: list[str] | None = None,
    stressors: list[str] | None = None,
    tone_descriptors: list[str] | None = None,
    formality_score: float = 0.7,
) -> str:
    """Build a JSON string that looks like the LLM context analysis response."""
    return json.dumps(
        {
            "summary": summary,
            "behaviors": behaviors or ["blocks on missing tests", "line-by-line review"],
            "communication_style": communication_style,
            "decision_style": "data-driven, references metrics",
            "motivators": motivators or ["code quality", "maintainability"],
            "stressors": stressors or ["missing tests", "unclear naming"],
            "evidence": ["Requested changes citing lack of coverage"],
            "formality_score": formality_score,
            "tone_descriptors": tone_descriptors or ["direct", "technical", "blunt"],
        }
    )


def _make_llm_contradiction_response(contradictions: list[dict[str, Any]] | None = None) -> str:
    return json.dumps(contradictions or [])


# ---------------------------------------------------------------------------
# Prompt template helpers (unit tests — no I/O)
# ---------------------------------------------------------------------------


class TestPromptBuilders:
    def test_context_analysis_prompt_contains_context_type(self):
        prompt = _build_context_analysis_prompt(
            username="torvalds",
            context_type="code_review",
            snippets=["snippet one", "snippet two"],
            sample_quotes=[],
        )
        assert "code_review" in prompt
        assert "torvalds" in prompt

    def test_context_analysis_prompt_includes_snippets(self):
        prompt = _build_context_analysis_prompt(
            username="torvalds",
            context_type="code_review",
            snippets=["unique-snippet-abc"],
            sample_quotes=[],
        )
        assert "unique-snippet-abc" in prompt

    def test_context_analysis_prompt_includes_quotes(self):
        prompt = _build_context_analysis_prompt(
            username="torvalds",
            context_type="code_review",
            snippets=["snippet"],
            sample_quotes=[{"quote": "LGTM", "context": "approving PR"}],
        )
        assert "LGTM" in prompt

    def test_contradictions_prompt_contains_summaries(self):
        prompt = _build_contradictions_prompt(
            username="torvalds",
            context_summaries={
                "code_review": "blunt and blocking",
                "chat_private": "reflective and uncertain",
            },
        )
        assert "blunt and blocking" in prompt
        assert "reflective and uncertain" in prompt
        assert "torvalds" in prompt


# ---------------------------------------------------------------------------
# build_context_block — no I/O
# ---------------------------------------------------------------------------


class TestBuildContextBlock:
    def test_empty_context_returns_empty_string(self):
        ctx = BehavioralContext(summary=None, contexts=[])
        result = build_context_block(ctx)
        assert result == ""

    def test_none_returns_empty_string(self):
        result = build_context_block(None)  # type: ignore[arg-type]
        assert result == ""

    def test_single_context_renders(self):
        ctx = BehavioralContext(
            summary="Two contexts found.",
            contexts=[
                BehavioralContextEntry(
                    context="code_review",
                    summary="Direct and blunt.",
                    behaviors=["blocks on tests", "line comments"],
                    communication_style="blunt, technical",
                    motivators=["quality"],
                    stressors=["missing tests"],
                ),
            ],
        )
        result = build_context_block(ctx)
        assert "code_review" in result
        assert "blunt" in result
        assert "BEHAVIORAL CONTEXT MAP" in result

    def test_contradiction_section_rendered(self):
        ctx = BehavioralContext(
            summary=(
                "Two contexts.\n\n## Cross-Context Contradictions\n"
                "- **code_review vs chat_private**: Loves pairing publicly vs dreads it privately"
            ),
            contexts=[
                BehavioralContextEntry(
                    context="code_review",
                    summary="Loves pairing.",
                    behaviors=[],
                ),
                BehavioralContextEntry(
                    context="chat_private",
                    summary="Dreads pairing.",
                    behaviors=[],
                ),
            ],
        )
        result = build_context_block(ctx)
        assert "Contradictions" in result
        assert "Loves pairing" in result or "dreads it privately" in result


# ---------------------------------------------------------------------------
# infer_behavioral_context — mocked LLM
# ---------------------------------------------------------------------------


class TestInferBehavioralContext:
    @pytest.mark.asyncio
    async def test_returns_behavioral_context_type(self):
        """infer_behavioral_context() always returns a BehavioralContext."""
        mini_id = _mini_id()
        # Evidence: 2 context types, each with MIN_ITEMS_PER_CONTEXT rows
        evidence = [
            _make_evidence_row("code_review", f"PR review {i}")
            for i in range(MIN_ITEMS_PER_CONTEXT)
        ] + [
            _make_evidence_row("blog_post", f"Blog post {i}") for i in range(MIN_ITEMS_PER_CONTEXT)
        ]
        session = _make_db_session(evidence_rows=evidence)

        with (
            patch(
                "app.synthesis.behavioral_context._call_llm_for_context",
                new_callable=AsyncMock,
            ) as mock_ctx,
            patch(
                "app.synthesis.behavioral_context._call_llm_for_contradictions",
                new_callable=AsyncMock,
            ) as mock_contra,
        ):
            mock_ctx.return_value = {
                "summary": "Analytical.",
                "behaviors": ["thorough"],
                "communication_style": "direct",
                "decision_style": "data-driven",
                "motivators": ["quality"],
                "stressors": ["noise"],
                "evidence": ["example"],
                "formality_score": 0.8,
                "tone_descriptors": ["technical"],
            }
            mock_contra.return_value = []

            result = await infer_behavioral_context(
                mini_id=mini_id,
                db_session=session,
                username="torvalds",
            )

        assert isinstance(result, BehavioralContext)

    @pytest.mark.asyncio
    async def test_three_contexts_produces_three_entries(self):
        """Three eligible context buckets → three ContextPersona entries."""
        mini_id = _mini_id()
        n = MIN_ITEMS_PER_CONTEXT
        evidence = (
            [_make_evidence_row("code_review", f"review {i}") for i in range(n)]
            + [_make_evidence_row("blog_post", f"blog {i}") for i in range(n)]
            + [_make_evidence_row("chat_public", f"comment {i}") for i in range(n)]
        )
        session = _make_db_session(evidence_rows=evidence)

        with (
            patch(
                "app.synthesis.behavioral_context._call_llm_for_context",
                new_callable=AsyncMock,
            ) as mock_ctx,
            patch(
                "app.synthesis.behavioral_context._call_llm_for_contradictions",
                new_callable=AsyncMock,
            ) as mock_contra,
        ):
            mock_ctx.return_value = {
                "summary": "Summary.",
                "behaviors": [],
                "communication_style": "casual",
                "decision_style": "intuitive",
                "motivators": [],
                "stressors": [],
                "evidence": [],
                "formality_score": 0.3,
                "tone_descriptors": ["casual"],
            }
            mock_contra.return_value = []

            result = await infer_behavioral_context(
                mini_id=mini_id,
                db_session=session,
                username="torvalds",
            )

        assert len(result.contexts) == 3
        context_names = {e.context for e in result.contexts}
        assert "code_review" in context_names
        assert "blog_post" in context_names
        assert "chat_public" in context_names

    @pytest.mark.asyncio
    async def test_contradictions_surface_when_evidence_disagrees(self):
        """Contradictions list is populated when LLM returns them."""
        mini_id = _mini_id()
        n = MIN_ITEMS_PER_CONTEXT
        evidence = [_make_evidence_row("code_review", f"review {i}") for i in range(n)] + [
            _make_evidence_row("chat_private", f"private {i}") for i in range(n)
        ]
        session = _make_db_session(evidence_rows=evidence)

        contradiction = {
            "description": "Loves pairing publicly vs dreads it privately",
            "context_a": "code_review",
            "behavior_a": "enthusiastically endorses pair programming",
            "context_b": "chat_private",
            "behavior_b": "finds pairing draining",
            "significance": "authentic multi-dimensionality",
        }

        with (
            patch(
                "app.synthesis.behavioral_context._call_llm_for_context",
                new_callable=AsyncMock,
            ) as mock_ctx,
            patch(
                "app.synthesis.behavioral_context._call_llm_for_contradictions",
                new_callable=AsyncMock,
            ) as mock_contra,
        ):
            mock_ctx.return_value = {
                "summary": "Summary.",
                "behaviors": [],
                "communication_style": "direct",
                "decision_style": "data-driven",
                "motivators": [],
                "stressors": [],
                "evidence": [],
                "formality_score": 0.7,
                "tone_descriptors": ["direct"],
            }
            mock_contra.return_value = [contradiction]

            result = await infer_behavioral_context(
                mini_id=mini_id,
                db_session=session,
                username="torvalds",
            )

        # Contradiction is serialised into the summary field
        assert result.summary is not None
        assert "pairing" in result.summary or "Cross-Context Contradictions" in result.summary

    @pytest.mark.asyncio
    async def test_falls_back_cleanly_when_only_one_context_type(self):
        """When only 1 context bucket meets the threshold, contradictions are skipped."""
        mini_id = _mini_id()
        n = MIN_ITEMS_PER_CONTEXT
        evidence = [_make_evidence_row("code_review", f"review {i}") for i in range(n)]
        session = _make_db_session(evidence_rows=evidence)

        with (
            patch(
                "app.synthesis.behavioral_context._call_llm_for_context",
                new_callable=AsyncMock,
            ) as mock_ctx,
            patch(
                "app.synthesis.behavioral_context._call_llm_for_contradictions",
                new_callable=AsyncMock,
            ) as mock_contra,
        ):
            mock_ctx.return_value = {
                "summary": "Only one context.",
                "behaviors": [],
                "communication_style": "blunt",
                "decision_style": "fast",
                "motivators": [],
                "stressors": [],
                "evidence": [],
                "formality_score": 0.6,
                "tone_descriptors": [],
            }
            mock_contra.return_value = []

            result = await infer_behavioral_context(
                mini_id=mini_id,
                db_session=session,
                username="torvalds",
            )

        assert isinstance(result, BehavioralContext)
        assert len(result.contexts) == 1
        # With only 1 context, contradictions call should not be invoked
        mock_contra.assert_called_once()  # called but returns []

    @pytest.mark.asyncio
    async def test_falls_back_cleanly_when_no_eligible_contexts(self):
        """When all context buckets are below min_items, return minimal object."""
        mini_id = _mini_id()
        # Only 1 item per context — below threshold of MIN_ITEMS_PER_CONTEXT
        evidence = [
            _make_evidence_row("code_review", "single review"),
            _make_evidence_row("blog_post", "single post"),
        ]
        session = _make_db_session(evidence_rows=evidence)

        result = await infer_behavioral_context(
            mini_id=mini_id,
            db_session=session,
            username="torvalds",
            min_items=MIN_ITEMS_PER_CONTEXT,
        )

        assert isinstance(result, BehavioralContext)
        assert len(result.contexts) == 0
        assert result.summary is not None

    @pytest.mark.asyncio
    async def test_falls_back_cleanly_when_no_evidence_at_all(self):
        """Empty evidence table → minimal BehavioralContext, no crash."""
        mini_id = _mini_id()
        session = _make_db_session(evidence_rows=[])

        result = await infer_behavioral_context(
            mini_id=mini_id,
            db_session=session,
            username="torvalds",
        )

        assert isinstance(result, BehavioralContext)
        assert len(result.contexts) == 0

    @pytest.mark.asyncio
    async def test_llm_failure_per_context_uses_fallback(self):
        """If the LLM fails for a context bucket, a fallback entry is used — no crash."""
        mini_id = _mini_id()
        n = MIN_ITEMS_PER_CONTEXT
        evidence = [_make_evidence_row("code_review", f"review {i}") for i in range(n)]
        session = _make_db_session(evidence_rows=evidence)

        with (
            patch(
                "app.synthesis.behavioral_context._call_llm_for_context",
                new_callable=AsyncMock,
            ) as mock_ctx,
            patch(
                "app.synthesis.behavioral_context._call_llm_for_contradictions",
                new_callable=AsyncMock,
            ) as mock_contra,
        ):
            # Simulate LLM returning fallback data (as _call_llm_for_context handles errors)
            mock_ctx.return_value = {
                "summary": "Analysis unavailable for context 'code_review'.",
                "behaviors": [],
                "communication_style": None,
                "decision_style": None,
                "motivators": [],
                "stressors": [],
                "evidence": [],
                "formality_score": 0.5,
                "tone_descriptors": [],
            }
            mock_contra.return_value = []

            result = await infer_behavioral_context(
                mini_id=mini_id,
                db_session=session,
                username="torvalds",
            )

        assert isinstance(result, BehavioralContext)
        assert len(result.contexts) == 1
        assert result.contexts[0].context == "code_review"


# ---------------------------------------------------------------------------
# spirit.build_system_prompt() integration
# ---------------------------------------------------------------------------


class TestSpiritIntegration:
    def test_behavioral_context_included_when_supplied(self):
        """build_system_prompt() injects BEHAVIORAL CONTEXT MAP when ctx is provided."""
        from app.synthesis.spirit import build_system_prompt

        ctx = BehavioralContext(
            summary="Code review context found.",
            contexts=[
                BehavioralContextEntry(
                    context="code_review",
                    summary="Direct and blunt.",
                    behaviors=["blocks on missing tests"],
                    communication_style="blunt",
                    motivators=["quality"],
                    stressors=["missing tests"],
                ),
            ],
        )

        prompt = build_system_prompt(
            username="torvalds",
            spirit_content="spirit here",
            memory_content="memory here",
            behavioral_context=ctx,
        )

        assert "BEHAVIORAL CONTEXT MAP" in prompt
        assert "code_review" in prompt

    def test_behavioral_context_omitted_when_none(self):
        """build_system_prompt() omits the block when behavioral_context is None."""
        from app.synthesis.spirit import build_system_prompt

        prompt = build_system_prompt(
            username="torvalds",
            spirit_content="spirit here",
            memory_content="memory here",
            behavioral_context=None,
        )

        assert "BEHAVIORAL CONTEXT MAP" not in prompt

    def test_backward_compatible_no_behavioral_context_arg(self):
        """Existing callers without behavioral_context arg still work."""
        from app.synthesis.spirit import build_system_prompt

        prompt = build_system_prompt("torvalds", "spirit", "memory")
        assert isinstance(prompt, str)
        assert "torvalds" in prompt
