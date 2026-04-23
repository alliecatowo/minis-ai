"""Tests for evidence and explorer progress models.

These tests verify model construction and default values without
requiring a database connection.
"""

import uuid

from app.models.evidence import (
    Evidence,
    ExplorerFinding,
    ExplorerProgress,
    ExplorerQuote,
    ReviewCycle,
)


class TestEvidenceModel:
    def test_create_evidence(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="commit",
            content="fix: resolve null pointer in auth module",
            context="commit_message",
        )
        assert ev.source_type == "github"
        assert ev.item_type == "commit"
        assert ev.content == "fix: resolve null pointer in auth module"
        assert ev.context == "commit_message"

    def test_evidence_explored_column_default(self):
        """Column default for explored is False (applied at DB insert time)."""
        col = Evidence.__table__.columns["explored"]
        assert col.default.arg is False

    def test_evidence_metadata_json_nullable(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="hackernews",
            item_type="comment",
            content="A comment",
            context="hackernews_comment",
            metadata_json={"url": "https://example.com", "score": 42},
        )
        assert ev.metadata_json["url"] == "https://example.com"
        assert ev.metadata_json["score"] == 42

    def test_evidence_metadata_json_default_none(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="pr",
            content="PR description",
        )
        assert ev.context is None
        assert ev.metadata_json is None

    def test_evidence_tablename(self):
        assert Evidence.__tablename__ == "evidence"

    def test_evidence_source_privacy_column_default(self):
        """source_privacy column default is 'public' (applied at DB insert time)."""
        col = Evidence.__table__.columns["source_privacy"]
        assert col.default.arg == "public"

    def test_evidence_source_privacy_can_be_set_to_private(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="claude_code",
            item_type="conversation",
            content="User said: let's use async/await everywhere",
            context="private_chat",
            source_privacy="private",
        )
        assert ev.context == "private_chat"
        assert ev.source_privacy == "private"

    def test_evidence_source_privacy_public(self):
        ev = Evidence(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            item_type="commit",
            content="fix: resolve null pointer",
            context="commit_message",
            source_privacy="public",
        )
        assert ev.context == "commit_message"
        assert ev.source_privacy == "public"

    def test_evidence_context_column_default(self):
        col = Evidence.__table__.columns["context"]
        assert col.default.arg == "general"


class TestExplorerFindingModel:
    def test_create_finding(self):
        f = ExplorerFinding(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            category="personality",
            content="Developer is meticulous about code review",
        )
        assert f.source_type == "github"
        assert f.category == "personality"
        assert f.content == "Developer is meticulous about code review"

    def test_finding_confidence_column_default(self):
        """Column default for confidence is 0.5 (applied at DB insert time)."""
        col = ExplorerFinding.__table__.columns["confidence"]
        assert col.default.arg == 0.5

    def test_finding_custom_confidence(self):
        f = ExplorerFinding(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="stackoverflow",
            category="skills",
            content="Expert in Python async",
            confidence=0.95,
        )
        assert f.confidence == 0.95

    def test_finding_tablename(self):
        assert ExplorerFinding.__tablename__ == "explorer_findings"


class TestExplorerQuoteModel:
    def test_create_quote(self):
        q = ExplorerQuote(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            quote="I'd rather have no abstraction than the wrong abstraction.",
            context="PR review comment on over-engineered factory pattern",
            significance="Shows preference for simplicity",
        )
        assert q.quote == "I'd rather have no abstraction than the wrong abstraction."
        assert q.context is not None
        assert q.significance is not None

    def test_quote_optional_fields(self):
        q = ExplorerQuote(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="hackernews",
            quote="Just ship it.",
        )
        assert q.context is None
        assert q.significance is None

    def test_quote_tablename(self):
        assert ExplorerQuote.__tablename__ == "explorer_quotes"


class TestExplorerProgressModel:
    def test_create_progress(self):
        p = ExplorerProgress(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
        )
        assert p.source_type == "github"

    def test_progress_count_column_defaults(self):
        """All count columns default to 0 (applied at DB insert time)."""
        table = ExplorerProgress.__table__
        for col_name in (
            "total_items",
            "explored_items",
            "findings_count",
            "memories_count",
            "quotes_count",
            "nodes_count",
        ):
            col = table.columns[col_name]
            assert col.default.arg == 0, f"{col_name} default should be 0"

    def test_progress_status_column_default(self):
        """Status column defaults to 'pending' (applied at DB insert time)."""
        col = ExplorerProgress.__table__.columns["status"]
        assert col.default.arg == "pending"

    def test_progress_optional_timestamps(self):
        p = ExplorerProgress(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
        )
        assert p.started_at is None
        assert p.finished_at is None
        assert p.summary is None

    def test_progress_custom_values(self):
        p = ExplorerProgress(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            total_items=100,
            explored_items=50,
            findings_count=12,
            status="in_progress",
            summary="Halfway through analysis",
        )
        assert p.total_items == 100
        assert p.explored_items == 50
        assert p.findings_count == 12
        assert p.status == "in_progress"
        assert p.summary == "Halfway through analysis"

    def test_progress_tablename(self):
        assert ExplorerProgress.__tablename__ == "explorer_progress"


class TestReviewCycleModel:
    def test_create_review_cycle(self):
        cycle = ReviewCycle(
            id=str(uuid.uuid4()),
            mini_id=str(uuid.uuid4()),
            source_type="github",
            external_id="repo:123:allie:deadbeef",
            predicted_state={
                "private_assessment": {"blocking_issues": [], "non_blocking_issues": []},
                "expressed_feedback": {"summary": "", "comments": []},
            },
        )
        assert cycle.source_type == "github"
        assert cycle.external_id == "repo:123:allie:deadbeef"
        assert cycle.predicted_state["private_assessment"]["blocking_issues"] == []
        assert cycle.human_review_outcome is None
        assert cycle.delta_metrics is None

    def test_review_cycle_source_type_default(self):
        col = ReviewCycle.__table__.columns["source_type"]
        assert col.default.arg == "github"

    def test_review_cycle_tablename(self):
        assert ReviewCycle.__tablename__ == "review_cycles"
