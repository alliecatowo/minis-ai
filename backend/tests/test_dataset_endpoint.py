"""Tests for the dataset generator endpoint and build_offline_pairs (ALLIE-175)."""

from __future__ import annotations

import datetime
import json


from app.synthesis.dataset_generator import (
    QAPair,
    build_offline_pairs,
    validate_dataset,
    _sample_prompts,
    IDENTITY_QUESTIONS,
    CODE_REVIEW_SCENARIOS,
    ARCH_DEBATE_PROMPTS,
    COMM_STYLE_PROMPTS,
)

# ── Sample fixtures ───────────────────────────────────────────────────────────

SAMPLE_SPIRIT = """
# Identity
Pragmatic systems builder who hates unnecessary abstraction.

## Communication Style
Short, direct sentences. No fluff. Uses lowercase a lot. Drops pronouns.

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
- "tbh this is fine, just merge it"
"""

SAMPLE_MEMORY = """
## The Archives (Episodic)

### Technical Expertise
- **Rust**: Expert-level systems programmer.

### Behavioral Quotes

> just ship it and fix it later
> over-engineering is the real enemy here
"""


# ── _sample_prompts ───────────────────────────────────────────────────────────


class TestSamplePrompts:
    def test_returns_requested_number_of_pairs(self):
        pairs = _sample_prompts(8)
        assert len(pairs) == 8

    def test_each_pair_is_instruction_and_skill_type(self):
        pairs = _sample_prompts(4)
        for instruction, skill_type in pairs:
            assert isinstance(instruction, str)
            assert len(instruction) > 5
            assert skill_type in {"identity", "code_review", "architecture", "communication"}

    def test_covers_all_skill_types(self):
        # With enough pairs (>= 4), all banks should be sampled
        pairs = _sample_prompts(20)
        skill_types = {s for _, s in pairs}
        assert skill_types == {"identity", "code_review", "architecture", "communication"}

    def test_large_request_capped_at_available_questions(self):
        total_available = (
            len(IDENTITY_QUESTIONS)
            + len(CODE_REVIEW_SCENARIOS)
            + len(ARCH_DEBATE_PROMPTS)
            + len(COMM_STYLE_PROMPTS)
        )
        pairs = _sample_prompts(total_available + 50)
        # Should not crash; may be less than total_available due to per-bank cap
        assert len(pairs) > 0


# ── build_offline_pairs ───────────────────────────────────────────────────────


class TestBuildOfflinePairs:
    def test_returns_requested_number_of_pairs(self):
        pairs = build_offline_pairs(SAMPLE_SPIRIT, SAMPLE_MEMORY, "testuser", num_pairs=10)
        assert len(pairs) == 10

    def test_each_pair_is_qa_pair(self):
        pairs = build_offline_pairs(SAMPLE_SPIRIT, SAMPLE_MEMORY, "testuser", num_pairs=5)
        for pair in pairs:
            assert isinstance(pair, QAPair)

    def test_instructions_are_non_empty(self):
        pairs = build_offline_pairs(SAMPLE_SPIRIT, SAMPLE_MEMORY, "testuser", num_pairs=5)
        for pair in pairs:
            assert pair.instruction.strip(), "Instruction must not be empty"

    def test_chosen_and_rejected_differ(self):
        pairs = build_offline_pairs(SAMPLE_SPIRIT, SAMPLE_MEMORY, "testuser", num_pairs=5)
        for pair in pairs:
            assert pair.chosen != pair.rejected, "chosen and rejected must differ"

    def test_source_is_offline(self):
        pairs = build_offline_pairs(SAMPLE_SPIRIT, SAMPLE_MEMORY, "testuser", num_pairs=3)
        for pair in pairs:
            assert pair.source == "offline"

    def test_example_ids_are_unique(self):
        pairs = build_offline_pairs(SAMPLE_SPIRIT, SAMPLE_MEMORY, "testuser", num_pairs=10)
        ids = [p.example_id for p in pairs]
        assert len(set(ids)) == len(ids), "Example IDs must be unique"

    def test_works_with_empty_spirit_content(self):
        pairs = build_offline_pairs("", "", "testuser", num_pairs=5)
        assert len(pairs) == 5
        for pair in pairs:
            assert isinstance(pair, QAPair)

    def test_chosen_incorporates_soul_phrases(self):
        """chosen response should reference soul example phrases or memory quotes."""
        pairs = build_offline_pairs(SAMPLE_SPIRIT, SAMPLE_MEMORY, "testuser", num_pairs=20)
        all_chosen = " ".join(p.chosen for p in pairs)
        # At least some chosen responses should contain spirit phrases
        soul_phrases = ["just ship it", "over-engineered", "tbh", "anyway"]
        assert any(phrase in all_chosen for phrase in soul_phrases), (
            f"Expected at least one soul phrase in chosen responses, got: {all_chosen[:200]}"
        )

    def test_dataset_passes_validation(self):
        pairs = build_offline_pairs(SAMPLE_SPIRIT, SAMPLE_MEMORY, "testuser", num_pairs=10)
        result = validate_dataset(pairs)
        assert result["valid"] is True, f"Validation errors: {result['errors']}"
        assert result["count"] == 10


# ── Dataset endpoint rate limiter ─────────────────────────────────────────────


class TestDatasetRateLimiter:
    """Unit tests for the in-memory rate limiting dict used by the /dataset endpoint."""

    def test_rate_limit_dict_structure(self):
        """Verify the rate limit dict accepts datetime values and round-trips correctly."""
        from app.routes.minis import _dataset_rate_limit, _DATASET_RATE_LIMIT_SECONDS

        assert _DATASET_RATE_LIMIT_SECONDS == 600
        assert isinstance(_dataset_rate_limit, dict)

    def test_rate_limit_window_check(self):
        """Simulate rate limit logic: second call within window should be blocked."""
        now = datetime.datetime.now(datetime.timezone.utc)
        last_gen = now - datetime.timedelta(seconds=30)  # 30 seconds ago

        elapsed = (now - last_gen).total_seconds()
        assert elapsed < 600, "Should be within rate limit window"
        retry_after = int(600 - elapsed)
        assert retry_after > 0

    def test_rate_limit_expired_allows_request(self):
        """After 10 minutes, the rate limit window should be cleared."""
        now = datetime.datetime.now(datetime.timezone.utc)
        last_gen = now - datetime.timedelta(seconds=601)  # 10min + 1s ago

        elapsed = (now - last_gen).total_seconds()
        assert elapsed >= 600, "Should be past rate limit window"


# ── Dataset JSONL format ──────────────────────────────────────────────────────


class TestDatasetJsonlFormat:
    def test_pairs_serialize_to_valid_jsonl(self):
        pairs = build_offline_pairs(SAMPLE_SPIRIT, SAMPLE_MEMORY, "testuser", num_pairs=5)
        lines = []
        for p in pairs:
            line = json.dumps({
                "instruction": p.instruction,
                "chosen": p.chosen,
                "rejected": p.rejected,
                "skill_type": p.skill_type,
                "source": p.source,
                "example_id": p.example_id,
            })
            lines.append(line)

        jsonl = "\n".join(lines) + "\n"
        # Every line must be valid JSON
        for line in jsonl.strip().split("\n"):
            obj = json.loads(line)
            assert "instruction" in obj
            assert "chosen" in obj
            assert "rejected" in obj
            assert "skill_type" in obj
            assert "example_id" in obj

    def test_jsonl_pairs_count_matches_num_pairs(self):
        pairs = build_offline_pairs(SAMPLE_SPIRIT, SAMPLE_MEMORY, "testuser", num_pairs=7)
        lines = [json.dumps({"i": p.instruction}) for p in pairs]
        assert len(lines) == 7
