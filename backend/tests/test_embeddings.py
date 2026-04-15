"""Tests for embedding utilities and the Embedding model.

Covers chunk_text logic and Embedding model construction. Does not make
real API calls — no GEMINI_API_KEY or OPENAI_API_KEY required.
"""

import uuid

from app.core.embeddings import chunk_text
from app.models.embeddings import Embedding


class TestChunkText:
    def test_basic_chunking(self):
        words = ["word"] * 1200
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=500)
        assert len(chunks) == 3
        assert all(c for c in chunks)

    def test_short_text_single_chunk(self):
        text = "Hello world this is a short sentence."
        chunks = chunk_text(text, chunk_size=500)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_exact_chunk_boundary(self):
        words = ["w"] * 1000
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=500)
        assert len(chunks) == 2
        for chunk in chunks:
            assert len(chunk.split()) == 500

    def test_empty_string_returns_empty_list(self):
        assert chunk_text("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert chunk_text("   \n\t  ") == []

    def test_custom_chunk_size(self):
        words = ["x"] * 10
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=3)
        # 10 words in groups of 3 → 4 chunks (3+3+3+1)
        assert len(chunks) == 4
        assert len(chunks[0].split()) == 3
        assert len(chunks[-1].split()) == 1

    def test_chunk_size_one(self):
        text = "a b c"
        chunks = chunk_text(text, chunk_size=1)
        assert chunks == ["a", "b", "c"]

    def test_chunks_are_non_empty_strings(self):
        text = "The quick brown fox jumps over the lazy dog"
        chunks = chunk_text(text, chunk_size=4)
        for chunk in chunks:
            assert isinstance(chunk, str)
            assert chunk.strip()

    def test_default_chunk_size(self):
        """Default chunk_size=500 produces a single chunk for short text."""
        text = "Short text."
        chunks = chunk_text(text)
        assert len(chunks) == 1

    def test_reassembly_covers_all_words(self):
        """Concatenating chunks recovers all original words."""
        words = ["word" + str(i) for i in range(1337)]
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size=100)
        reassembled = " ".join(chunks)
        assert reassembled == text


class TestEmbeddingModel:
    def _fake_vector(self) -> list[float]:
        return [0.0] * 768

    def test_create_embedding(self):
        emb = Embedding(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            content="Developer prefers composition over inheritance.",
            embedding=self._fake_vector(),
            source_type="memory",
        )
        assert emb.content == "Developer prefers composition over inheritance."
        assert emb.source_type == "memory"
        assert len(emb.embedding) == 768

    def test_embedding_tablename(self):
        assert Embedding.__tablename__ == "embeddings"

    def test_embedding_id_default(self):
        """id column has a callable UUID default factory."""
        col = Embedding.__table__.columns["id"]
        # The default is a callable (lambda), not a static value
        assert callable(col.default.arg)

    def test_embedding_metadata_json_nullable(self):
        emb = Embedding(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            content="Some content",
            embedding=self._fake_vector(),
            source_type="evidence",
            metadata_json={"chunk_index": 0, "total_chunks": 3},
        )
        assert emb.metadata_json["chunk_index"] == 0
        assert emb.metadata_json["total_chunks"] == 3

    def test_embedding_metadata_json_default_none(self):
        emb = Embedding(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            content="Some content",
            embedding=self._fake_vector(),
            source_type="knowledge_node",
        )
        assert emb.metadata_json is None

    def test_source_type_variants(self):
        for source in ("memory", "evidence", "knowledge_node"):
            emb = Embedding(
                id=str(uuid.uuid4()),
                mini_id=str(uuid.uuid4()),
                content="content",
                embedding=self._fake_vector(),
                source_type=source,
            )
            assert emb.source_type == source
