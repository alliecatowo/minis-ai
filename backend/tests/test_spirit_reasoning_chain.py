from app.synthesis.spirit import build_system_prompt


def test_reasoning_chain_block_present_for_opinion_questions() -> None:
    prompt = build_system_prompt("testuser", "spirit")

    assert "SYNTHESIS, NOT RETRIEVAL" in prompt
    assert "synthes" in prompt.lower()
    assert "the goal is not tool count — it is reasoning depth" in prompt
