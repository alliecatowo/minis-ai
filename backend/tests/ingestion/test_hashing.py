"""Tests for content hashing helper (ALLIE-374 M1)."""

from __future__ import annotations

from app.ingestion.hashing import hash_evidence_content


class TestHashEvidenceContent:
    def test_same_content_same_hash(self):
        h1 = hash_evidence_content("hello world")
        h2 = hash_evidence_content("hello world")
        assert h1 == h2

    def test_returns_64_char_hex(self):
        digest = hash_evidence_content("some content")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_whitespace_only_change_same_hash(self):
        """Leading/trailing whitespace is stripped before hashing."""
        h1 = hash_evidence_content("hello world")
        h2 = hash_evidence_content("  hello world  ")
        h3 = hash_evidence_content("\nhello world\n")
        assert h1 == h2 == h3

    def test_different_content_different_hash(self):
        h1 = hash_evidence_content("content A")
        h2 = hash_evidence_content("content B")
        assert h1 != h2

    def test_metadata_reorder_same_hash(self):
        """Metadata key order doesn't affect the hash (canonical JSON)."""
        h1 = hash_evidence_content("content", metadata={"a": 1, "b": 2})
        h2 = hash_evidence_content("content", metadata={"b": 2, "a": 1})
        assert h1 == h2

    def test_metadata_none_vs_empty_dict(self):
        """None metadata and an empty dict should produce the same hash."""
        h1 = hash_evidence_content("content", metadata=None)
        h2 = hash_evidence_content("content", metadata=None)
        assert h1 == h2

    def test_metadata_changes_hash(self):
        """Different metadata produces a different hash for the same content."""
        h1 = hash_evidence_content("content", metadata={"pr": 1})
        h2 = hash_evidence_content("content", metadata={"pr": 2})
        assert h1 != h2

    def test_no_metadata_vs_with_metadata_differ(self):
        """Content-only hash differs from content+metadata hash."""
        h1 = hash_evidence_content("content")
        h2 = hash_evidence_content("content", metadata={"key": "value"})
        assert h1 != h2

    def test_empty_metadata_dict_ignored(self):
        """Empty metadata dict adds nothing to the hash (falsy check)."""
        h1 = hash_evidence_content("content")
        h2 = hash_evidence_content("content", metadata={})
        assert h1 == h2
