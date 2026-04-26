from app.synthesis.spirit import build_system_prompt


def test_reasoning_chain_block_present_for_opinion_questions() -> None:
    prompt = build_system_prompt("testuser", "spirit")

    assert "REASONING CHAIN" in prompt
    assert "synthes" in prompt.lower()
    assert "Required 5-step chain" in prompt
    assert "single tool call is failure" in prompt
    assert "1. `search_memories`" in prompt
    assert "2. `search_evidence`" in prompt
    assert "3. `think`" in prompt
    assert "4. Re-`think`" in prompt
    assert "5. Compose the final answer." in prompt
