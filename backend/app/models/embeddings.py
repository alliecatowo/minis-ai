"""Model for storing vector embeddings for memory/evidence retrieval."""

import datetime
import uuid

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
