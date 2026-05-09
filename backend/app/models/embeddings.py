"""Model for storing vector embeddings plus shared retrieval helpers."""

import datetime
import re
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mini import Base


class Embedding(Base):
    """Vector embedding keyed by source table row and chunk index."""

    __tablename__ = "embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mini_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("minis.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    row_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    chunk_index: Mapped[int | None] = mapped_column(nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    vector: Mapped[list | None] = mapped_column(Vector(1536), nullable=True)
    embedding: Mapped[list | None] = mapped_column(Vector(768), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # memory | evidence | knowledge_node
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "table_name",
            "row_id",
            "chunk_index",
            name="uq_embeddings_table_row_chunk",
        ),
        Index("ix_embeddings_mini_table_name", "mini_id", "table_name"),
    )


RETRIEVAL_DEFAULT_BUDGET = 8
RETRIEVAL_MAX_SNIPPET_CHARS = 700
RETRIEVAL_CONTEXT_RADIUS = 2


def normalize_snippet(text: str, *, max_chars: int = RETRIEVAL_MAX_SNIPPET_CHARS) -> str:
    """Deterministically normalize and cap snippet size for retrieval output."""
    compact = " ".join((text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def query_keywords(query: str) -> list[str]:
    terms = [token.lower() for token in re.findall(r"[a-z0-9_]{2,}", query or "")]
    return sorted(set(terms))


def lexical_windows(
    content: str,
    query: str,
    *,
    max_results: int = RETRIEVAL_DEFAULT_BUDGET,
    context_radius: int = RETRIEVAL_CONTEXT_RADIUS,
    source_label: str = "lexical",
) -> list[dict[str, Any]]:
    """Return deterministic lexical windows scored by keyword overlap."""
    if not content or not content.strip():
        return []

    lines = content.split("\n")
    keywords = query_keywords(query)
    if not keywords:
        keywords = [query.lower().strip()] if query and query.strip() else []
    if not keywords:
        return []

    scored: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        line_lower = line.lower()
        score = sum(1 for kw in keywords if kw in line_lower)
        if score > 0:
            scored.append((score, idx))
    scored.sort(key=lambda item: (-item[0], item[1]))

    windows: list[dict[str, Any]] = []
    seen_line_indexes: set[int] = set()
    for score, idx in scored:
        if idx in seen_line_indexes:
            continue
        start = max(0, idx - context_radius)
        end = min(len(lines), idx + context_radius + 1)
        for line_index in range(start, end):
            seen_line_indexes.add(line_index)
        snippet = "\n".join(lines[start:end]).strip()
        if not snippet:
            continue
        windows.append(
            {
                "content": normalize_snippet(snippet),
                "lexical_score": score / max(1, len(keywords)),
                "semantic_score": 0.0,
                "provenance_score": 0.25,
                "source": source_label,
                "row_id": None,
                "chunk_index": idx,
                "citation": f"{source_label}:L{start + 1}-L{end}",
            }
        )
        if len(windows) >= max_results:
            break

    return windows


def blend_hybrid_matches(
    query: str,
    *,
    semantic_matches: list[dict[str, Any]] | None = None,
    lexical_matches: list[dict[str, Any]] | None = None,
    budget: int = RETRIEVAL_DEFAULT_BUDGET,
) -> list[dict[str, Any]]:
    """Blend semantic + lexical + provenance signals with deterministic ranking."""
    keyword_count = max(1, len(query_keywords(query)))
    candidates: list[dict[str, Any]] = []

    for match in semantic_matches or []:
        content = normalize_snippet(str(match.get("content") or ""))
        if not content:
            continue
        semantic_score = float(match.get("score") or 0.0)
        lexical_hits = sum(1 for kw in query_keywords(query) if kw in content.lower())
        lexical_score = lexical_hits / keyword_count
        row_id = str(match.get("row_id") or "").strip() or None
        table_name = str(match.get("table_name") or "").strip() or "unknown"
        chunk_index = int(match.get("chunk_index") or 0)
        provenance_score = 1.0 if row_id else 0.4
        citation = f"{table_name}:{row_id or 'n/a'}#{chunk_index}"
        candidates.append(
            {
                "content": content,
                "semantic_score": semantic_score,
                "lexical_score": lexical_score,
                "provenance_score": provenance_score,
                "source": table_name,
                "row_id": row_id,
                "chunk_index": chunk_index,
                "citation": citation,
            }
        )

    for match in lexical_matches or []:
        content = normalize_snippet(str(match.get("content") or ""))
        if not content:
            continue
        candidates.append(
            {
                "content": content,
                "semantic_score": float(match.get("semantic_score") or 0.0),
                "lexical_score": float(match.get("lexical_score") or 0.0),
                "provenance_score": float(match.get("provenance_score") or 0.0),
                "source": str(match.get("source") or "lexical"),
                "row_id": str(match.get("row_id") or "").strip() or None,
                "chunk_index": int(match.get("chunk_index") or 0),
                "citation": str(match.get("citation") or "lexical"),
            }
        )

    for candidate in candidates:
        candidate["hybrid_score"] = (
            0.65 * candidate["semantic_score"]
            + 0.25 * candidate["lexical_score"]
            + 0.10 * candidate["provenance_score"]
        )

    candidates.sort(
        key=lambda item: (
            -item["hybrid_score"],
            -item["semantic_score"],
            -item["lexical_score"],
            -item["provenance_score"],
            item["source"],
            item["row_id"] or "",
            item["chunk_index"],
            item["content"],
        )
    )

    deduped: list[dict[str, Any]] = []
    seen_snippets: set[str] = set()
    for candidate in candidates:
        snippet_key = candidate["content"].lower()
        if snippet_key in seen_snippets:
            continue
        seen_snippets.add(snippet_key)
        deduped.append(candidate)
        if len(deduped) >= max(1, budget):
            break

    return deduped
