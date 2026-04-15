"""Tests for spirit.py — system prompt builder.

Covers:
- build_system_prompt() with spirit + memory produces structured output
- build_system_prompt() with empty inputs still produces a usable prompt
- Expected section headers are present
- username is embedded in the output
- Memory section is included only when memory_content is non-empty
"""

from __future__ import annotations

import pytest

from app.synthesis.spirit import build_system_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


EXPECTED_SECTIONS = [
    "IDENTITY DIRECTIVE",
    "PERSONALITY & STYLE",
    "ANTI-VALUES",
    "BEHAVIORAL GUIDELINES",
    "SYSTEM PROMPT PROTECTION",
]


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


class TestBuildSystemPromptStructure:
    def test_returns_string(self):
        result = build_system_prompt("torvalds", "spirit content")
        assert isinstance(result, str)

    def test_non_empty_result(self):
        result = build_system_prompt("torvalds", "spirit content")
        assert len(result) > 100

    def test_identity_directive_section_present(self):
        result = build_system_prompt("testuser", "spirit")
        assert "IDENTITY DIRECTIVE" in result

    def test_personality_style_section_present(self):
        result = build_system_prompt("testuser", "spirit")
        assert "PERSONALITY & STYLE" in result

    def test_anti_values_section_present(self):
        result = build_system_prompt("testuser", "spirit")
        assert "ANTI-VALUES" in result

    def test_behavioral_guidelines_section_present(self):
        result = build_system_prompt("testuser", "spirit")
        assert "BEHAVIORAL GUIDELINES" in result

    def test_system_prompt_protection_section_present(self):
        result = build_system_prompt("testuser", "spirit")
        assert "SYSTEM PROMPT PROTECTION" in result

    def test_all_expected_sections_present(self):
        result = build_system_prompt("testuser", "spirit content here")
        for section in EXPECTED_SECTIONS:
            assert section in result, f"Missing section: {section}"


# ---------------------------------------------------------------------------
# Username embedding
# ---------------------------------------------------------------------------


class TestUsernameEmbedding:
    def test_username_appears_in_identity_directive(self):
        result = build_system_prompt("linus_torvalds", "spirit content")
        assert "linus_torvalds" in result

    def test_username_appears_multiple_times(self):
        username = "unique_test_user_xyz"
        result = build_system_prompt(username, "spirit content")
        count = result.count(username)
        assert count >= 2, f"Username should appear multiple times, got {count}"

    def test_you_are_username_in_identity(self):
        result = build_system_prompt("dhh", "some spirit")
        assert "You ARE dhh" in result or "you are dhh" in result.lower()


# ---------------------------------------------------------------------------
# Spirit content embedding
# ---------------------------------------------------------------------------


class TestSpiritContentEmbedding:
    def test_spirit_content_appears_in_output(self):
        spirit = "This developer is highly opinionated about code quality."
        result = build_system_prompt("testuser", spirit)
        assert spirit in result

    def test_empty_spirit_still_returns_prompt(self):
        result = build_system_prompt("testuser", "")
        assert isinstance(result, str)
        assert len(result) > 100

    def test_whitespace_spirit_handled_gracefully(self):
        result = build_system_prompt("testuser", "   \n   ")
        assert isinstance(result, str)
        assert len(result) > 100


# ---------------------------------------------------------------------------
# Memory content
# ---------------------------------------------------------------------------


class TestMemoryContent:
    def test_knowledge_section_present_when_memory_provided(self):
        result = build_system_prompt("testuser", "spirit", memory_content="memory here")
        assert "KNOWLEDGE" in result

    def test_memory_content_appears_in_knowledge_section(self):
        memory = "Builds distributed systems using Go and Kubernetes."
        result = build_system_prompt("testuser", "spirit", memory_content=memory)
        assert memory in result

    def test_knowledge_section_absent_when_no_memory(self):
        result = build_system_prompt("testuser", "spirit", memory_content="")
        assert "# KNOWLEDGE" not in result

    def test_knowledge_section_absent_when_memory_default(self):
        # Default memory_content="" should skip the KNOWLEDGE section
        result = build_system_prompt("testuser", "spirit")
        assert "# KNOWLEDGE" not in result

    def test_memory_content_default_is_empty(self):
        """Without memory_content the KNOWLEDGE block should not appear."""
        result_without = build_system_prompt("testuser", "spirit content")
        result_with = build_system_prompt(
            "testuser", "spirit content", memory_content="some memory"
        )
        assert "# KNOWLEDGE" not in result_without
        assert "# KNOWLEDGE" in result_with


# ---------------------------------------------------------------------------
# Anti-values section content
# ---------------------------------------------------------------------------


class TestAntiValuesSection:
    def test_universal_donts_listed(self):
        result = build_system_prompt("testuser", "spirit")
        assert "DON'T" in result or "NEVER" in result

    def test_never_say_great_question_listed(self):
        result = build_system_prompt("testuser", "spirit")
        assert "Great question" in result or "great question" in result.lower()

    def test_never_break_character_instruction(self):
        result = build_system_prompt("testuser", "spirit")
        assert "break character" in result.lower() or "NEVER break character" in result


# ---------------------------------------------------------------------------
# Prompt protection section
# ---------------------------------------------------------------------------


class TestPromptProtection:
    def test_protection_section_tells_to_never_reveal(self):
        result = build_system_prompt("testuser", "spirit")
        assert "NEVER reveal" in result or "Do NOT repeat" in result

    def test_protection_mentions_system_prompt(self):
        result = build_system_prompt("testuser", "spirit")
        assert "system prompt" in result.lower()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_username_with_special_chars(self):
        """Usernames like 'john-doe' or 'john_doe' should work."""
        result = build_system_prompt("john-doe", "spirit content")
        assert "john-doe" in result

    def test_long_spirit_content_preserved(self):
        """Long spirit content should appear verbatim in the output."""
        spirit = "A " * 5000  # 10000 chars
        result = build_system_prompt("testuser", spirit)
        assert spirit in result

    def test_long_memory_content_preserved(self):
        memory = "B " * 5000
        result = build_system_prompt("testuser", "spirit", memory_content=memory)
        assert memory in result

    def test_result_contains_four_pillar_reference(self):
        """The prompt should mention the four-pillar structure."""
        result = build_system_prompt("testuser", "spirit")
        assert "PERSONALITY" in result
        assert "STYLE" in result
        assert "VALUES" in result
        assert "KNOWLEDGE" in result
