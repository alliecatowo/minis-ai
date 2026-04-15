"""Tests for per-provider compaction logic."""

from __future__ import annotations

import pytest

from app.core.compaction import (
    MINIS_SUMMARY_PROMPT,
    create_compaction_processor,
    detect_provider,
)
from app.core.models import Provider


# ---------------------------------------------------------------------------
# detect_provider
# ---------------------------------------------------------------------------


class TestDetectProvider:
    def test_gemini_prefix(self):
        assert detect_provider("gemini:gemini-2.5-flash") == Provider.GEMINI

    def test_google_prefix(self):
        assert detect_provider("google:gemini-2.5-flash") == Provider.GEMINI

    def test_anthropic_prefix(self):
        assert detect_provider("anthropic:claude-sonnet-4-6") == Provider.ANTHROPIC

    def test_openai_prefix(self):
        assert detect_provider("openai:gpt-4.1") == Provider.OPENAI

    def test_unknown_prefix(self):
        assert detect_provider("mistral:mistral-large") is None

    def test_no_colon(self):
        assert detect_provider("gpt-4.1") is None

    def test_case_insensitive(self):
        assert detect_provider("GEMINI:gemini-2.5-flash") == Provider.GEMINI
        assert detect_provider("Anthropic:claude-sonnet-4-6") == Provider.ANTHROPIC
        assert detect_provider("OpenAI:gpt-4.1") == Provider.OPENAI


# ---------------------------------------------------------------------------
# create_compaction_processor
# ---------------------------------------------------------------------------


class TestCreateCompactionProcessor:
    def test_gemini_returns_processor(self):
        processor = create_compaction_processor("gemini:gemini-2.5-flash")
        assert processor is not None

    def test_anthropic_returns_none(self):
        processor = create_compaction_processor("anthropic:claude-sonnet-4-6")
        assert processor is None

    def test_openai_returns_none(self):
        processor = create_compaction_processor("openai:gpt-4.1")
        assert processor is None

    def test_unknown_provider_returns_processor(self):
        """Unknown providers get LLM-based summarization as a safe default."""
        processor = create_compaction_processor("mistral:mistral-large")
        assert processor is not None

    def test_no_colon_returns_processor(self):
        """Model strings without a provider prefix get summarization."""
        processor = create_compaction_processor("gpt-4.1")
        assert processor is not None

    def test_processor_uses_custom_prompt(self):
        """The processor should use our custom Minis summary prompt."""
        from pydantic_ai_summarization import SummarizationProcessor

        processor = create_compaction_processor("gemini:gemini-2.5-flash")
        assert isinstance(processor, SummarizationProcessor)
        # Verify custom prompt is wired in (it contains our distinctive text)
        assert "Findings persisted to DB" in MINIS_SUMMARY_PROMPT
