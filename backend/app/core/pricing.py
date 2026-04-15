"""Model pricing and cost calculation for LLM metering."""

# Prices per 1M tokens (USD)
# Keys use PydanticAI model string format ("provider:model-name")
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Gemini
    "gemini:gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini:gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini:gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    # OpenAI
    "openai:gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "openai:gpt-4.1": {"input": 2.00, "output": 8.00},
    "openai:o4-mini": {"input": 1.10, "output": 4.40},
    # Anthropic
    "anthropic:claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    "anthropic:claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}

# Fallback pricing for unknown models (conservative estimate)
DEFAULT_PRICING: dict[str, float] = {"input": 1.00, "output": 3.00}


def calculate_cost(
    model: str, input_tokens: int, output_tokens: int
) -> float:
    """Calculate USD cost for a completion given token counts.

    Returns cost in USD (e.g. 0.00015 for a small request).
    """
    pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost
