"""Embedding utilities for vector storage and semantic retrieval."""

from __future__ import annotations

import os

import httpx

from app.core.models import ModelTier, Provider, get_model

_GEMINI_EMBED_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
_OPENAI_EMBED_URL = "https://api.openai.com/v1/embeddings"
_MAX_EMBED_BATCH = 100


def _resolve_embedding_model() -> tuple[str, str]:
    """Return (provider_name, model_name) for the active embedding tier."""
    model_str = get_model(ModelTier.EMBEDDING)
    if ":" in model_str:
        provider_str, model_name = model_str.split(":", 1)
    else:
        provider_str = Provider.GEMINI
        model_name = model_str
    return provider_str, model_name


async def embed_text(text: str) -> list[float]:
    """Embed a single text string."""
    vectors = await embed_texts([text])
    return vectors[0]


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Backward-compatible alias for batched embeddings."""
    return await embed_texts(texts)


async def embed_texts(texts: list[str], batch_size: int = _MAX_EMBED_BATCH) -> list[list[float]]:
    """Generate embeddings in async batches (max 100 texts per API call)."""
    cleaned = [t for t in texts if isinstance(t, str) and t.strip()]
    if not cleaned:
        return []

    provider_str, model_name = _resolve_embedding_model()
    results: list[list[float]] = []

    for start in range(0, len(cleaned), batch_size):
        batch = cleaned[start : start + batch_size]
        if provider_str == Provider.OPENAI:
            results.extend(await _embed_openai_batch(batch, model_name))
        else:
            results.extend(await _embed_gemini_batch(batch, model_name))

    return results


def chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """Split text into non-overlapping whitespace chunks."""
    if not text or not text.strip():
        return []

    words = text.split()
    chunks: list[str] = []
    for i in range(0, len(words), chunk_size):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks


async def _embed_gemini_batch(texts: list[str], model_name: str) -> list[list[float]]:
    """Gemini REST endpoint is single-input; issue per-item calls for the batch."""
    vectors: list[list[float]] = []
    for text in texts:
        vectors.append(await _embed_gemini(text, model_name))
    return vectors


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


async def _embed_openai_batch(texts: list[str], model_name: str) -> list[list[float]]:
    api_key = os.environ.get("OPENAI_API_KEY", "")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _OPENAI_EMBED_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model_name, "input": texts},
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data.get("data", [])]
