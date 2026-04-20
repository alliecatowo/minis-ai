"""Embedding utilities for generating and chunking text for vector storage.

Uses the Gemini text-embedding-004 model via direct HTTP call (768 dimensions).
Provider routing respects the DEFAULT_PROVIDER env var — falls back to Gemini
when the active provider doesn't define an EMBEDDING tier model.
"""

import os

import httpx

from app.core.models import ModelTier, Provider, get_model

# Gemini embedding endpoint
_GEMINI_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"

# OpenAI embedding endpoint
_OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings"


def _resolve_embedding_model() -> tuple[str, str]:
    """Return (provider_name, model_name) for the active embedding tier."""
    model_str = get_model(ModelTier.EMBEDDING)
    # model_str is "provider:model-name"
    if ":" in model_str:
        provider_str, model_name = model_str.split(":", 1)
    else:
        provider_str = "gemini"
        model_name = model_str
    return provider_str, model_name


async def embed_text(text: str) -> list[float]:
    """Generate a 768-dimensional embedding vector for a single text string.

    Routes to Gemini or OpenAI based on DEFAULT_PROVIDER. Raises on API errors.
    """
    provider_str, model_name = _resolve_embedding_model()

    if provider_str == Provider.OPENAI:
        return await _embed_openai(text, model_name)

    # Default: Gemini
    return await _embed_gemini(text, model_name)


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Generate embedding vectors for a list of texts.

    Makes individual calls sequentially — Gemini's batch API is not yet
    exposed via the REST endpoint used here.
    """
    results: list[list[float]] = []
    for text in texts:
        results.append(await embed_text(text))
    return results


def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """Split text into overlapping chunks of approximately chunk_size words.

    Splits on whitespace, groups into chunks, and returns non-empty strings.
    No overlap is applied — chunks are consecutive, non-overlapping word groups.
    """
    if not text or not text.strip():
        return []

    words = text.split()
    chunks: list[str] = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# Provider-specific helpers
# ---------------------------------------------------------------------------


async def _embed_gemini(text: str, model_name: str) -> list[float]:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    url = _GEMINI_EMBED_URL.format(model=model_name)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            params={"key": api_key},
            json={"model": f"models/{model_name}", "content": {"parts": [{"text": text}]}},
        )
        response.raise_for_status()
        data = response.json()
        return data["embedding"]["values"]


async def _embed_openai(text: str, model_name: str) -> list[float]:
    api_key = os.environ.get("OPENAI_API_KEY", "")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _OPENAI_EMBED_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model_name, "input": text},
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]
