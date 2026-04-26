from dataclasses import dataclass

from app.synthesis.spirit import build_system_prompt


@dataclass
class FakeMini:
    spirit_content: str


def test_build_system_prompt_starts_with_register_match_and_references_typing_register() -> None:
    mini = FakeMini(spirit_content="## TYPING REGISTER\n- **Capitalization habit**: lowercase")

    prompt = build_system_prompt("testuser", mini.spirit_content)

    assert prompt.startswith("REGISTER MATCH:")
    assert "TYPING REGISTER" in prompt
