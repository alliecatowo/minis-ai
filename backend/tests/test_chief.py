"""Tests for backend/app/synthesis/chief.py — constants and prompt integrity."""

from __future__ import annotations

from app.synthesis.chief import (
    AUTHENTICITY_LOOP_SYNTHESIS_BLOCK,
    CHIEF_FINAL_SYNTHESIS_PROMPT,
    NARRATIVE_ASPECTS,
    SECTION_ORDER,
    SYSTEM_PROMPT,
)


class TestSectionOrder:
    def test_contains_eight_sections(self):
        assert len(SECTION_ORDER) == 8

    def test_soul_document_first(self):
        assert SECTION_ORDER[0] == "soul_document"

    def test_no_duplicates(self):
        assert len(SECTION_ORDER) == len(set(SECTION_ORDER))


class TestNarrativeAspects:
    def test_contains_thirteen_aspects(self):
        assert len(NARRATIVE_ASPECTS) == 13

    def test_no_duplicates(self):
        assert len(NARRATIVE_ASPECTS) == len(set(NARRATIVE_ASPECTS))

    def test_includes_required_aspects(self):
        required = {
            "voice_signature",
            "decision_frameworks",
            "code_philosophy",
            "collaboration_style",
            "personality_typology",
            "motivations_drivers",
        }
        assert required.issubset(set(NARRATIVE_ASPECTS))


class TestSystemPrompt:
    def test_system_prompt_nonempty(self):
        assert SYSTEM_PROMPT and len(SYSTEM_PROMPT) > 100

    def test_chief_final_synthesis_prompt_nonempty(self):
        assert CHIEF_FINAL_SYNTHESIS_PROMPT and len(CHIEF_FINAL_SYNTHESIS_PROMPT) > 100

    def test_authenticity_loop_block_nonempty(self):
        assert AUTHENTICITY_LOOP_SYNTHESIS_BLOCK and len(AUTHENTICITY_LOOP_SYNTHESIS_BLOCK) > 50
