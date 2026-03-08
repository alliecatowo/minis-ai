"""Unit tests for dataset_generator.py (ALLIE-89/90/91)."""

from __future__ import annotations

import pytest

from app.synthesis.dataset_generator import (
    DatasetGenerationConfig,
    QAPair,
    SoulDocumentParser,
    SoulProfile,
    build_spirit_system_prompt,
    extract_behavioral_quotes,
    route_to_skill,
    validate_dataset,
)


# ── 1. DatasetGenerationConfig validation ─────────────────────────────────────


def test_dataset_generation_config_defaults():
    cfg = DatasetGenerationConfig(mini_id="user-123")
    assert cfg.num_pairs == 80
    assert cfg.temperature == 0.85
    assert cfg.base_llm == "claude-3-5-haiku-latest"
    assert cfg.output_dir is None


def test_dataset_generation_config_bounds():
    with pytest.raises(Exception):
        DatasetGenerationConfig(mini_id="x", num_pairs=5)  # below ge=10
    with pytest.raises(Exception):
        DatasetGenerationConfig(mini_id="x", num_pairs=300)  # above le=200
    with pytest.raises(Exception):
        DatasetGenerationConfig(mini_id="x", temperature=2.5)  # above le=2.0


# ── 2. SoulDocumentParser ─────────────────────────────────────────────────────


SAMPLE_SPIRIT = """
# Identity
Pragmatic systems builder who hates unnecessary abstraction.

## Communication Style
Short, direct sentences. No fluff. Uses lowercase a lot.

## Values
- Simplicity over cleverness
- Ship it then iterate
- Honest feedback, even when uncomfortable

## Quirks
- Says "tbh" constantly
- Ends rants with "anyway"

## Example Phrases
- "just ship it"
- "that's over-engineered"
"""


def test_soul_document_parser_extracts_sections():
    parser = SoulDocumentParser()
    profile = parser.parse(SAMPLE_SPIRIT)

    assert isinstance(profile, SoulProfile)
    assert "direct" in profile.communication_style or "Short" in profile.communication_style
    assert len(profile.values) >= 2
    assert any("simplicity" in v.lower() for v in profile.values)
    assert len(profile.quirks) >= 1
    assert len(profile.example_phrases) >= 1


def test_soul_document_parser_empty_document():
    parser = SoulDocumentParser()
    profile = parser.parse("")
    assert profile.communication_style == ""
    assert profile.values == []
    assert profile.quirks == []


# ── 3. extract_behavioral_quotes ─────────────────────────────────────────────


def test_extract_behavioral_quotes_blockquotes():
    memory = """
## Behavioral Evidence

> just ship it and fix it later
> don't over-engineer things you haven't built yet
Some prose that is not a quote.
"""
    quotes = extract_behavioral_quotes(memory, max_quotes=10)
    assert len(quotes) >= 2
    assert any("ship it" in q for q in quotes)


def test_extract_behavioral_quotes_respects_max():
    lines = "\n".join(f"> quote number {i} about something interesting" for i in range(30))
    quotes = extract_behavioral_quotes(lines, max_quotes=5)
    assert len(quotes) <= 5


# ── 4. route_to_skill ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "instruction,expected",
    [
        ("Can you review this PR? The function opens a DB connection in a loop.", "code_review"),
        ("Microservices vs monolith — where do you land?", "architecture"),
        ("How do you write a good RFC?", "communication"),
        ("SQL vs NoSQL for a new microservice database schema?", "architecture"),
        ("Tell me about your approach to learning new languages", "identity"),
    ],
)
def test_route_to_skill(instruction: str, expected: str):
    result = route_to_skill(instruction)
    assert result == expected


# ── 5. validate_dataset ───────────────────────────────────────────────────────


def test_validate_dataset_valid():
    pairs = [
        QAPair(
            instruction="How do you handle code reviews?",
            chosen="I keep it blunt. If the code is bad, I say so.",
            rejected="That is a great question! There are several considerations when approaching code reviews.",
            skill_type="code_review",
            example_id="abc123",
        )
    ]
    result = validate_dataset(pairs)
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["count"] == 1


def test_validate_dataset_identical_chosen_rejected():
    pairs = [
        QAPair(
            instruction="What do you think of TDD?",
            chosen="It's fine in theory.",
            rejected="It's fine in theory.",
            skill_type="identity",
        )
    ]
    result = validate_dataset(pairs)
    assert result["valid"] is False
    assert any("identical" in e for e in result["errors"])


def test_validate_dataset_empty_instruction():
    pairs = [
        QAPair(
            instruction="   ",
            chosen="Some response here that is long enough.",
            rejected="Another response here that is also long enough.",
            skill_type="identity",
        )
    ]
    result = validate_dataset(pairs)
    assert result["valid"] is False
    assert any("instruction is empty" in e for e in result["errors"])


def test_validate_dataset_unknown_skill_type_is_warning_not_error():
    pairs = [
        QAPair(
            instruction="How do you approach debugging?",
            chosen="I add print statements everywhere first, honestly.",
            rejected="There are several systematic debugging methodologies worth considering.",
            skill_type="totally_made_up_skill",
        )
    ]
    result = validate_dataset(pairs)
    assert result["valid"] is True  # unknown skill is a warning, not an error
    assert any("unknown skill_type" in w for w in result["warnings"])


def test_validate_dataset_empty_list():
    result = validate_dataset([])
    assert result["valid"] is True
    assert result["count"] == 0
    assert result["errors"] == []
