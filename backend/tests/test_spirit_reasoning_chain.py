from app.synthesis.spirit import build_system_prompt


def test_abductive_authenticity_loop_present() -> None:
    prompt = build_system_prompt("testuser", "spirit")

    assert "ABDUCTIVE AUTHENTICITY LOOP" in prompt
    assert "synthes" in prompt.lower()
    assert "SYNTHESIS, NOT RETRIEVAL" in prompt
    # Regression guard: the loop teaches via principles, not tool-count coercion.
    assert "single tool call is failure" not in prompt
