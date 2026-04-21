"""Tests for ALLIE-440: ExplorerQuote + context_evidence survive DB-path report reconstruction.

Covers:
- Unit: _build_synthetic_reports_from_db returns behavioral_quotes + context_evidence
- Unit: _combine_report_text includes quotes and context buckets
- Regression: existing findings/memories still present in reports
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest

from app.synthesis.explorers.base import ExplorerReport, MemoryEntry
from app.synthesis.memory_assembler import _combine_report_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(findings=None, quotes=None, context_rows=None):
    """Return an async context-manager session factory that yields a mock session."""
    findings = findings or []
    quotes = quotes or []
    context_rows = context_rows or []

    async def _execute(stmt):
        # Peek at which model is being queried by the WHERE clause column.
        # We rely on call order: findings first, quotes second, context third.
        mock_result = MagicMock()
        return mock_result

    # We'll return different scalars/all on each call
    call_count = 0
    all_results = [findings, quotes, context_rows]

    class _Session:
        async def execute(self, stmt):
            nonlocal call_count
            result = MagicMock()
            data = all_results[call_count % len(all_results)]
            call_count += 1
            if call_count <= 2:
                # findings and quotes use .scalars().all()
                scalars = MagicMock()
                scalars.all.return_value = data
                result.scalars.return_value = scalars
            else:
                # context rows use .all() directly
                result.all.return_value = data
            return result

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    @asynccontextmanager
    async def factory():
        yield _Session()

    return factory


def _make_finding(mini_id, source_type="github", category="personality", content="detailed content"):
    f = MagicMock()
    f.mini_id = mini_id
    f.source_type = source_type
    f.category = category
    f.content = content
    f.confidence = 0.8
    return f


def _make_quote(mini_id, source_type="github", quote="I prefer explicit over implicit", context="code_review", significance="communication_style"):
    q = MagicMock()
    q.mini_id = mini_id
    q.source_type = source_type
    q.quote = quote
    q.context = context
    q.significance = significance
    return q


def _make_context_row(source_type="github", context="code_review", content="some evidence text"):
    row = MagicMock()
    row.source_type = source_type
    row.context = context
    row.content = content
    return row


# ---------------------------------------------------------------------------
# _combine_report_text — unit tests (ALLIE-440)
# ---------------------------------------------------------------------------


class TestCombineReportText:
    def test_includes_personality_findings(self):
        report = ExplorerReport(
            source_name="github",
            personality_findings="pragmatic engineer",
        )
        text = _combine_report_text([report])
        assert "pragmatic engineer" in text

    def test_includes_memory_entries_when_flag_set(self):
        entry = MemoryEntry(
            category="projects",
            topic="main project",
            content="built a distributed system",
            confidence=0.9,
            source_type="github",
        )
        report = ExplorerReport(
            source_name="github",
            personality_findings="",
            memory_entries=[entry],
        )
        text = _combine_report_text([report], include_entries=True)
        assert "distributed system" in text

    def test_excludes_memory_entries_when_flag_false(self):
        entry = MemoryEntry(
            category="projects",
            topic="main project",
            content="built a distributed system",
            confidence=0.9,
            source_type="github",
        )
        report = ExplorerReport(
            source_name="github",
            personality_findings="opinionated",
            memory_entries=[entry],
        )
        text = _combine_report_text([report], include_entries=False)
        assert "distributed system" not in text
        assert "opinionated" in text

    def test_includes_behavioral_quotes(self):
        """ALLIE-440: behavioral_quotes must appear in combined text."""
        report = ExplorerReport(
            source_name="github",
            personality_findings="",
            behavioral_quotes=[
                {"context": "code_review", "quote": "LGTM but simplify", "signal_type": "communication_style"}
            ],
        )
        text = _combine_report_text([report])
        assert "LGTM but simplify" in text

    def test_behavioral_quote_includes_signal_type_label(self):
        report = ExplorerReport(
            source_name="github",
            personality_findings="",
            behavioral_quotes=[
                {"context": "", "quote": "ship it", "signal_type": "decisive"}
            ],
        )
        text = _combine_report_text([report])
        assert "[quote/decisive]" in text
        assert "ship it" in text

    def test_behavioral_quote_includes_context_annotation(self):
        report = ExplorerReport(
            source_name="github",
            personality_findings="",
            behavioral_quotes=[
                {"context": "PR comment", "quote": "nit: typo", "signal_type": "detail_oriented"}
            ],
        )
        text = _combine_report_text([report])
        assert "PR comment" in text
        assert "nit: typo" in text

    def test_includes_context_evidence_buckets(self):
        """ALLIE-440: context_evidence must appear in combined text."""
        report = ExplorerReport(
            source_name="github",
            personality_findings="",
            context_evidence={
                "code_review": ["great catch, fixed"],
                "documentation": ["added inline docs"],
            },
        )
        text = _combine_report_text([report])
        assert "great catch, fixed" in text
        assert "added inline docs" in text

    def test_context_evidence_includes_bucket_label(self):
        report = ExplorerReport(
            source_name="github",
            personality_findings="",
            context_evidence={"casual_chat": ["lol no way"]},
        )
        text = _combine_report_text([report])
        assert "[casual_chat]" in text
        assert "lol no way" in text

    def test_empty_quotes_and_context_do_not_add_noise(self):
        report = ExplorerReport(
            source_name="github",
            personality_findings="solid",
        )
        text = _combine_report_text([report])
        assert text == "solid"

    def test_multiple_reports_combined(self):
        r1 = ExplorerReport(
            source_name="github",
            personality_findings="rust expert",
            behavioral_quotes=[{"context": "", "quote": "unsafe is fine here", "signal_type": "opinionated"}],
        )
        r2 = ExplorerReport(
            source_name="blog",
            personality_findings="writer",
            context_evidence={"public_writing": ["I think tests matter"]},
        )
        text = _combine_report_text([r1, r2])
        assert "rust expert" in text
        assert "unsafe is fine here" in text
        assert "writer" in text
        assert "I think tests matter" in text


# ---------------------------------------------------------------------------
# _build_synthetic_reports_from_db — integration-style unit tests (ALLIE-440)
# ---------------------------------------------------------------------------


class TestBuildSyntheticReportsFromDb:
    """These tests mock the DB session factory so no real DB is needed."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_data(self):
        from app.synthesis.pipeline import _build_synthetic_reports_from_db

        factory = _make_session_factory(findings=[], quotes=[], context_rows=[])
        result = await _build_synthetic_reports_from_db("mini-1", factory)
        assert result == []

    @pytest.mark.asyncio
    async def test_findings_populate_personality_parts(self):
        from app.synthesis.pipeline import _build_synthetic_reports_from_db

        mini_id = str(uuid.uuid4())
        finding = _make_finding(mini_id, category="personality", content="values simplicity")
        factory = _make_session_factory(findings=[finding], quotes=[], context_rows=[])
        reports = await _build_synthetic_reports_from_db(mini_id, factory)
        assert len(reports) == 1
        assert "values simplicity" in reports[0].personality_findings

    @pytest.mark.asyncio
    async def test_quotes_populate_behavioral_quotes(self):
        """ALLIE-440: ExplorerQuote rows must appear in behavioral_quotes."""
        from app.synthesis.pipeline import _build_synthetic_reports_from_db

        mini_id = str(uuid.uuid4())
        quote = _make_quote(mini_id, quote="ship fast, fix faster", context="standup", significance="pragmatic")
        factory = _make_session_factory(findings=[], quotes=[quote], context_rows=[])
        reports = await _build_synthetic_reports_from_db(mini_id, factory)
        assert len(reports) == 1
        bq = reports[0].behavioral_quotes
        assert len(bq) == 1
        assert bq[0]["quote"] == "ship fast, fix faster"
        assert bq[0]["context"] == "standup"
        assert bq[0]["signal_type"] == "pragmatic"

    @pytest.mark.asyncio
    async def test_context_rows_populate_context_evidence(self):
        """ALLIE-440: Evidence context buckets must appear in context_evidence."""
        from app.synthesis.pipeline import _build_synthetic_reports_from_db

        mini_id = str(uuid.uuid4())
        ctx_row = _make_context_row(source_type="github", context="code_review", content="nit: rename this var")
        factory = _make_session_factory(findings=[], quotes=[], context_rows=[ctx_row])
        reports = await _build_synthetic_reports_from_db(mini_id, factory)
        assert len(reports) == 1
        ce = reports[0].context_evidence
        assert "code_review" in ce
        assert any("nit: rename this var" in s for s in ce["code_review"])

    @pytest.mark.asyncio
    async def test_combine_all_signal_types(self):
        """All three sources of signal survive into one report when from same source_type."""
        from app.synthesis.pipeline import _build_synthetic_reports_from_db

        mini_id = str(uuid.uuid4())
        finding = _make_finding(mini_id, source_type="github", category="personality", content="detail-oriented")
        quote = _make_quote(mini_id, source_type="github", quote="always add tests", context="PR", significance="quality")
        ctx_row = _make_context_row(source_type="github", context="documentation", content="explains trade-offs well")
        factory = _make_session_factory(findings=[finding], quotes=[quote], context_rows=[ctx_row])
        reports = await _build_synthetic_reports_from_db(mini_id, factory)

        assert len(reports) == 1
        r = reports[0]
        assert "detail-oriented" in r.personality_findings
        assert any(q["quote"] == "always add tests" for q in r.behavioral_quotes)
        assert "documentation" in r.context_evidence

    @pytest.mark.asyncio
    async def test_confidence_summary_mentions_all_counts(self):
        from app.synthesis.pipeline import _build_synthetic_reports_from_db

        mini_id = str(uuid.uuid4())
        finding = _make_finding(mini_id)
        quote = _make_quote(mini_id)
        ctx_row = _make_context_row()
        factory = _make_session_factory(findings=[finding], quotes=[quote], context_rows=[ctx_row])
        reports = await _build_synthetic_reports_from_db(mini_id, factory)
        assert len(reports) == 1
        summary = reports[0].confidence_summary
        assert "finding" in summary
        assert "quote" in summary
        assert "context" in summary
