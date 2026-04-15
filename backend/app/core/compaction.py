"""Per-provider compaction for long-running agent conversations.

Detects the model provider and applies the appropriate compaction strategy:

- **Gemini** (and other providers without native compaction): Uses
  ``summarization-pydantic-ai`` to LLM-summarize history when context grows
  too large.  The FAST tier model is used for the summarization call.
- **Anthropic**: Returns ``None`` — Anthropic supports native server-side
  compaction via the ``compact-2026-01-12`` beta header.  The caller should
  set ``extra_headers={"anthropic-beta": "interleaved-thinking-2025-05-14,
  prompt-caching-2025-04-14"}`` and ``max_tokens`` with a ``context_window``
  model setting to enable it.  No history_processor is needed.
- **OpenAI**: Returns ``None`` — OpenAI supports native API compaction via
  ``context_management.compact_threshold``.  The caller should pass the
  appropriate model_settings to enable it.  No history_processor is needed.
"""

from __future__ import annotations

import logging

from app.core.models import ModelTier, Provider, get_model

logger = logging.getLogger(__name__)

# Custom summary prompt that preserves task-relevant context for Minis agents
MINIS_SUMMARY_PROMPT = """\
<role>
Context Preservation Assistant for an AI agent pipeline
</role>

<primary_objective>
Extract and preserve the most important context from this conversation so the
agent can continue its work without losing track of progress.
</primary_objective>

<instructions>
The conversation history will be replaced with your summary. Preserve:

1. **Task state**: What is the agent currently working on? What was the
   original request?
2. **Progress**: What steps have been completed? What tools were called and
   what were the key results?
3. **Findings persisted to DB**: Any data that was saved (explorer reports,
   soul documents, memory documents, knowledge graph entries).
4. **Remaining work**: What steps are left? What decisions are pending?
5. **Key data**: Important names, URLs, code snippets, or identifiers that
   the agent will need to reference.

Omit: verbose tool output that has already been processed, duplicate
information, and conversational filler.
</instructions>

Respond ONLY with the extracted context. No preamble.

<messages>
{messages}
</messages>"""


def detect_provider(model_string: str) -> Provider | None:
    """Detect the provider from a PydanticAI model string.

    Model strings use the format ``provider:model-name`` (e.g.
    ``gemini:gemini-2.5-flash``).  Returns ``None`` if the provider prefix
    is not recognised.
    """
    if ":" not in model_string:
        return None

    prefix = model_string.split(":")[0].lower()
    provider_map: dict[str, Provider] = {
        "gemini": Provider.GEMINI,
        "google": Provider.GEMINI,
        "anthropic": Provider.ANTHROPIC,
        "openai": Provider.OPENAI,
    }
    return provider_map.get(prefix)


def create_compaction_processor(
    model_string: str,
    user_override: str | None = None,
):
    """Create a PydanticAI ``history_processor`` for context compaction.

    Returns a ``SummarizationProcessor`` for providers that lack native
    compaction (Gemini and unknown providers), or ``None`` for providers
    with native compaction support (Anthropic, OpenAI).

    Args:
        model_string: The PydanticAI model string for the *primary* agent
            model (e.g. ``"gemini:gemini-2.5-flash"``).  Used to detect the
            provider.
        user_override: Optional user-level model override passed through to
            ``get_model`` when resolving the FAST tier summarization model.

    Returns:
        A ``SummarizationProcessor`` instance or ``None``.
    """
    provider = detect_provider(model_string)

    # Anthropic and OpenAI have native compaction — no processor needed
    if provider in (Provider.ANTHROPIC, Provider.OPENAI):
        logger.debug(
            "Provider %s supports native compaction; skipping history_processor",
            provider,
        )
        return None

    # For Gemini and all other providers, use LLM-based summarization
    from pydantic_ai_summarization import create_summarization_processor

    fast_model = get_model(ModelTier.FAST, user_override)
    logger.debug(
        "Creating summarization processor for provider=%s using fast model=%s",
        provider,
        fast_model,
    )

    return create_summarization_processor(
        model=fast_model,
        trigger=("messages", 40),
        keep=("messages", 10),
        summary_prompt=MINIS_SUMMARY_PROMPT,
    )
