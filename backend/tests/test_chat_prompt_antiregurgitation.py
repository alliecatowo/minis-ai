from __future__ import annotations

from app.routes.chat import _strip_voice_samples_block
from app.synthesis.spirit import build_system_prompt


def test_build_system_prompt_includes_anti_regurgitation_block() -> None:
    prompt = build_system_prompt(
        username="testdev",
        spirit_content="# Identity\nYou are direct.",
        memory_content="",
    )

    assert "ANTI-REGURGITATION" in prompt


def test_strip_voice_samples_block_removes_literal_quotes_section() -> None:
    prompt = """# PERSONALITY\nYou are concise.\n\nVoice Samples:\n- \"exact phrase one\"\n- \"exact phrase two\"\n\n# VALUES\nBe practical.\n"""

    stripped = _strip_voice_samples_block(prompt)

    assert "Voice Samples:" not in stripped
    assert "exact phrase one" not in stripped
    assert "exact phrase two" not in stripped
    assert "# VALUES" in stripped
