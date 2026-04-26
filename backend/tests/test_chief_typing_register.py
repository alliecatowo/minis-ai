from app.synthesis.chief import ASPECT_GUIDANCE


def test_voice_signature_guidance_requires_typing_register_axes() -> None:
    guidance = ASPECT_GUIDANCE["voice_signature"]

    assert "TYPING REGISTER" in guidance
    assert "Capitalization habit" in guidance
    assert "Apostrophe usage" in guidance
    assert "Comma vs period punctuation" in guidance
    assert "Profanity tolerance" in guidance
    assert "Spelling discipline" in guidance
    assert "Sentence fragmentation" in guidance
