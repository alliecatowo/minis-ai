"""Model hierarchy and tier system for LLM provider management.

Every model reference in the codebase goes through this module.
Users can override defaults via settings or per-request overrides.
"""

from __future__ import annotations

import os
from enum import StrEnum



class ModelTier(StrEnum):
    FAST = "fast"           # Compaction, summaries, classifications
    STANDARD = "standard"   # Explorer agents, chat, tool-calling
    THINKING = "thinking"   # Complex synthesis, soul documents
    EMBEDDING = "embedding" # Vector embeddings


class Provider(StrEnum):
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


# Provider defaults using PydanticAI model string format ("provider:model-name")
PROVIDER_DEFAULTS: dict[Provider, dict[ModelTier, str]] = {
    Provider.GEMINI: {
        ModelTier.FAST: "google-gla:gemini-2.5-flash",
        ModelTier.STANDARD: "google-gla:gemini-2.5-flash",
        ModelTier.THINKING: "google-gla:gemini-2.5-pro",
        ModelTier.EMBEDDING: "google-gla:text-embedding-004",
    },
    Provider.ANTHROPIC: {
        ModelTier.FAST: "anthropic:claude-haiku-4-5",
        ModelTier.STANDARD: "anthropic:claude-sonnet-4-6",
        ModelTier.THINKING: "anthropic:claude-sonnet-4-6",
    },
    Provider.OPENAI: {
        ModelTier.FAST: "openai:gpt-4.1-mini",
        ModelTier.STANDARD: "openai:gpt-4.1",
        ModelTier.THINKING: "openai:o4-mini",
        ModelTier.EMBEDDING: "openai:text-embedding-3-small",
    },
}


def _detect_default_provider() -> Provider:
    """Detect the default provider from env vars."""
    env_provider = os.environ.get("DEFAULT_PROVIDER", "gemini").lower()
    try:
        return Provider(env_provider)
    except ValueError:
        return Provider.GEMINI


def get_model(
    tier: ModelTier = ModelTier.STANDARD,
    user_override: str | None = None,
) -> str:
    """Resolve a model string for the given tier.

    Resolution order:
    1. User override (if provided) — returned as-is
    2. Provider defaults for the system's default provider
    3. Gemini fallback (always available)

    Returns a PydanticAI model string like "gemini:gemini-2.5-flash".
    """
    if user_override:
        return user_override

    provider = _detect_default_provider()
    provider_models = PROVIDER_DEFAULTS.get(provider, {})

    if tier in provider_models:
        return provider_models[tier]

    # Fallback to Gemini defaults
    gemini_models = PROVIDER_DEFAULTS[Provider.GEMINI]
    if tier in gemini_models:
        return gemini_models[tier]

    # Ultimate fallback
    return "google-gla:gemini-2.5-flash"


def get_default_model() -> str:
    """Get the default standard-tier model. Convenience wrapper."""
    return get_model(ModelTier.STANDARD)
