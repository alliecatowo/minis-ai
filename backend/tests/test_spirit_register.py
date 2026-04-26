from dataclasses import dataclass

from app.synthesis.spirit import build_system_prompt


@dataclass
class FakeMini:
    spirit_content: str


def test_build_system_prompt_includes_abductive_loop_and_references_typing_register() -> None:
    mini = FakeMini(spirit_content="## TYPING REGISTER\n- **Capitalization habit**: lowercase")

    prompt = build_system_prompt("testuser", mini.spirit_content)

    assert "ABDUCTIVE AUTHENTICITY LOOP" in prompt
    assert "TYPING REGISTER" in prompt
