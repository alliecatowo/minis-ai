from __future__ import annotations

from types import SimpleNamespace

from app.synthesis.prompt_renderer import (
    CHAT_PROMPT_PRESET,
    TEAM_CHAT_PROMPT_PRESET,
    build_current_work_vs_deep_loves_block,
    render_runtime_system_prompt,
)


def _mini(
    *,
    system_prompt: str | None = "You are testdev.",
    spirit_content: str | None = None,
    memory_content: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        system_prompt=system_prompt,
        spirit_content=spirit_content,
        memory_content=memory_content,
    )


def test_chat_team_presets_share_common_option_values() -> None:
    assert CHAT_PROMPT_PRESET.strip_voice_samples == TEAM_CHAT_PROMPT_PRESET.strip_voice_samples
    assert CHAT_PROMPT_PRESET.prepend_spirit_content == TEAM_CHAT_PROMPT_PRESET.prepend_spirit_content
    assert CHAT_PROMPT_PRESET.append_search_hint == TEAM_CHAT_PROMPT_PRESET.append_search_hint
    assert (
        CHAT_PROMPT_PRESET.append_current_work_vs_deep_loves
        == TEAM_CHAT_PROMPT_PRESET.append_current_work_vs_deep_loves
    )
    assert (
        CHAT_PROMPT_PRESET.append_recency_vs_preference
        == TEAM_CHAT_PROMPT_PRESET.append_recency_vs_preference
    )
    assert (
        CHAT_PROMPT_PRESET.append_tool_use_directive
        == TEAM_CHAT_PROMPT_PRESET.append_tool_use_directive
    )


def test_chat_team_render_parity_for_shared_options() -> None:
    mini = _mini(
        spirit_content="deep_loves: Nuxt and long-term frontend architecture",
        memory_content="currently building async runtime tooling",
    )

    chat_prompt = render_runtime_system_prompt(mini, CHAT_PROMPT_PRESET)
    team_prompt = render_runtime_system_prompt(mini, TEAM_CHAT_PROMPT_PRESET)

    assert chat_prompt == team_prompt
    assert "# TOOL USE" in chat_prompt
    assert "Current Work vs Deep Loves" in chat_prompt


def test_prefix_requires_original_system_prompt() -> None:
    mini_without_base = _mini(system_prompt=None, spirit_content="you are direct")
    rendered = render_runtime_system_prompt(
        mini_without_base,
        TEAM_CHAT_PROMPT_PRESET,
        system_prompt_prefix="WARNING: ",
    )

    assert not rendered.startswith("WARNING:")


def test_current_work_vs_deep_loves_block_extracts_fields() -> None:
    block = build_current_work_vs_deep_loves_block(
        spirit_content="current_focus: Shipping Rust runtime\nframework_loves: Nuxt architecture",
        memory_content="",
    )

    assert "Shipping Rust runtime" in block
    assert "Nuxt architecture" in block
