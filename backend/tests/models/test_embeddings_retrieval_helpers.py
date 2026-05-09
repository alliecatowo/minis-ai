from __future__ import annotations

from app.models.embeddings import blend_hybrid_matches, lexical_windows, normalize_snippet


def test_normalize_snippet_is_bounded_and_deterministic():
    text = "word " * 400
    a = normalize_snippet(text, max_chars=120)
    b = normalize_snippet(text, max_chars=120)
    assert a == b
    assert len(a) <= 120


def test_lexical_windows_budget_and_order_are_deterministic():
    content = "\n".join(
        [
            "python and rust together",
            "filler",
            "only rust here",
            "only python here",
        ]
    )
    first = lexical_windows(content, "python rust", max_results=2, source_label="memory")
    second = lexical_windows(content, "python rust", max_results=2, source_label="memory")
    assert first == second
    assert len(first) == 2
    assert "python and rust together" in first[0]["content"]


def test_blend_hybrid_matches_keeps_budget_and_prefers_semantic_signal():
    matches = blend_hybrid_matches(
        "rollback safety",
        semantic_matches=[
            {
                "table_name": "explorer_findings",
                "row_id": "mem-1",
                "chunk_index": 0,
                "content": "Rollback plans and release safety checks are required.",
                "score": 0.92,
            }
        ],
        lexical_matches=[
            {
                "content": "release checklist",
                "lexical_score": 1.0,
                "provenance_score": 0.25,
                "source": "memory",
                "citation": "memory:L1-L1",
            }
        ],
        budget=1,
    )

    assert len(matches) == 1
    assert matches[0]["citation"].startswith("explorer_findings:mem-1#")
