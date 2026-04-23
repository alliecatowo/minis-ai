"""Integration tests for durable review-cycle persistence."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.evidence import ExplorerFinding, ExplorerQuote, ReviewCycle
from app.models.schemas import (
    ReviewCycleOutcomeUpdateRequest,
    ReviewCyclePredictionUpsertRequest,
    StructuredReviewState,
)
from app.review_cycles import finalize_review_cycle, upsert_review_cycle_prediction
from app.synthesis.pipeline import _build_synthetic_reports_from_db

_CREATE_MINIS = """
CREATE TABLE IF NOT EXISTS minis (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_REVIEW_CYCLES = """
CREATE TABLE IF NOT EXISTS review_cycles (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'github',
    external_id TEXT NOT NULL,
    metadata_json JSON,
    predicted_state_json JSON NOT NULL,
    human_review_outcome_json JSON,
    delta_metrics_json JSON,
    predicted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    human_reviewed_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_review_cycles_mini_source_external_id UNIQUE (mini_id, source_type, external_id)
)
"""

_CREATE_EVIDENCE = """
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    item_type TEXT NOT NULL,
    content TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT 'general',
    metadata_json JSON,
    source_privacy TEXT NOT NULL DEFAULT 'public',
    explored BOOLEAN NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    external_id TEXT,
    last_fetched_at TEXT,
    content_hash TEXT,
    ai_contamination_score FLOAT,
    ai_contamination_checked_at TEXT
)
"""

_CREATE_EXPLORER_FINDINGS = """
CREATE TABLE IF NOT EXISTS explorer_findings (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.5,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""

_CREATE_EXPLORER_QUOTES = """
CREATE TABLE IF NOT EXISTS explorer_quotes (
    id TEXT PRIMARY KEY,
    mini_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    quote TEXT NOT NULL,
    context TEXT,
    significance TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


def _review_state(summary: str, approval_state: str) -> StructuredReviewState:
    return StructuredReviewState.model_validate(
        {
            "private_assessment": {
                "blocking_issues": [{"id": "missing-tests"}],
                "non_blocking_issues": [],
                "open_questions": [],
                "positive_signals": [],
                "confidence": 0.8,
            },
            "delivery_policy": {
                "author_model": "trusted_peer",
                "context": "normal",
                "strictness": "medium",
                "teaching_mode": True,
                "shield_author_from_noise": True,
            },
            "expressed_feedback": {
                "summary": summary,
                "comments": [{"path": "app.py", "body": summary}],
                "approval_state": approval_state,
            },
        }
    )


@pytest.fixture(scope="module")
def engine():
    return create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest_asyncio.fixture(scope="module")
async def tables(engine):
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_MINIS))
        await conn.execute(text(_CREATE_REVIEW_CYCLES))
        await conn.execute(text(_CREATE_EVIDENCE))
        await conn.execute(text(_CREATE_EXPLORER_FINDINGS))
        await conn.execute(text(_CREATE_EXPLORER_QUOTES))
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS explorer_quotes"))
        await conn.execute(text("DROP TABLE IF EXISTS explorer_findings"))
        await conn.execute(text("DROP TABLE IF EXISTS evidence"))
        await conn.execute(text("DROP TABLE IF EXISTS review_cycles"))
        await conn.execute(text("DROP TABLE IF EXISTS minis"))
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine, tables):
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        mini_id = str(uuid.uuid4())
        await s.execute(
            text(
                "INSERT INTO minis (id, username, status) VALUES (:id, :username, 'ready')"
            ),
            {"id": mini_id, "username": f"user-{mini_id[:8]}"},
        )
        await s.commit()
        yield s, mini_id
        await s.execute(text("DELETE FROM explorer_quotes"))
        await s.execute(text("DELETE FROM explorer_findings"))
        await s.execute(text("DELETE FROM evidence"))
        await s.execute(text("DELETE FROM review_cycles"))
        await s.execute(text("DELETE FROM minis"))
        await s.commit()


class TestReviewCyclePersistence:
    @pytest.mark.asyncio
    async def test_upsert_then_finalize_updates_single_row(self, session):
        db, mini_id = session
        external_id = "acme/widgets#123:allie:deadbeef"

        created = await upsert_review_cycle_prediction(
            db,
            mini_id,
            ReviewCyclePredictionUpsertRequest(
                external_id=external_id,
                source_type="github",
                metadata_json={"repo_full_name": "acme/widgets", "pr_number": 123},
                predicted_state=_review_state("Please add tests.", "request_changes"),
            ),
        )

        assert created.external_id == external_id
        assert created.human_review_outcome is None
        assert created.delta_metrics is None

        finalized = await finalize_review_cycle(
            db,
            mini_id,
            ReviewCycleOutcomeUpdateRequest(
                external_id=external_id,
                source_type="github",
                human_review_outcome=_review_state("Nit only, otherwise fine.", "comment"),
                delta_metrics={
                    "github_review_state": "COMMENTED",
                    "github_review_id": 987,
                },
            ),
        )

        assert finalized is not None
        assert finalized.id == created.id
        assert finalized.human_review_outcome["expressed_feedback"]["approval_state"] == "comment"
        assert finalized.delta_metrics["approval_state_changed"] is True
        assert finalized.delta_metrics["predicted_approval_state"] == "request_changes"
        assert finalized.delta_metrics["actual_approval_state"] == "comment"
        assert finalized.delta_metrics["github_review_id"] == 987
        assert finalized.human_reviewed_at is not None

        count_result = await db.execute(select(func.count()).select_from(ReviewCycle))
        assert count_result.scalar_one() == 1

        stored_result = await db.execute(
            select(ReviewCycle).where(
                ReviewCycle.mini_id == mini_id,
                ReviewCycle.source_type == "github",
                ReviewCycle.external_id == external_id,
            )
        )
        stored = stored_result.scalar_one()
        assert stored.predicted_state["expressed_feedback"]["approval_state"] == "request_changes"
        assert stored.human_review_outcome["expressed_feedback"]["summary"] == "Nit only, otherwise fine."

    @pytest.mark.asyncio
    async def test_finalize_writes_review_learning_back_into_synthesis_inputs(self, session):
        db, mini_id = session
        external_id = "acme/widgets#456:allie:feedface"

        await upsert_review_cycle_prediction(
            db,
            mini_id,
            ReviewCyclePredictionUpsertRequest(
                external_id=external_id,
                source_type="github",
                metadata_json={"repo_full_name": "acme/widgets", "pr_number": 456},
                predicted_state=_review_state("Block on test gap.", "request_changes"),
            ),
        )

        await finalize_review_cycle(
            db,
            mini_id,
            ReviewCycleOutcomeUpdateRequest(
                external_id=external_id,
                source_type="github",
                human_review_outcome=_review_state("Nit only, otherwise fine.", "comment"),
                delta_metrics={},
            ),
        )

        findings_result = await db.execute(
            select(ExplorerFinding).where(
                ExplorerFinding.mini_id == mini_id,
                ExplorerFinding.source_type == "review_writeback",
            )
        )
        findings = findings_result.scalars().all()
        assert len(findings) == 1
        assert findings[0].category == "decision_patterns"
        assert "predicted approval_state=request_changes" in findings[0].content
        assert "actual approval_state=comment" in findings[0].content
        assert "approval_state_changed=yes" in findings[0].content
        assert "Nit only, otherwise fine." in findings[0].content

        quotes_result = await db.execute(
            select(ExplorerQuote).where(
                ExplorerQuote.mini_id == mini_id,
                ExplorerQuote.source_type == "review_writeback",
            )
        )
        quotes = quotes_result.scalars().all()
        assert len(quotes) == 1
        assert quotes[0].quote == "Nit only, otherwise fine."
        assert quotes[0].significance == "review_outcome"

        async_session = sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
        reports = await _build_synthetic_reports_from_db(mini_id, async_session)
        review_reports = [report for report in reports if report.source_name == "review_writeback"]
        assert len(review_reports) == 1
        assert "actual approval_state=comment" in review_reports[0].personality_findings
        assert any(
            quote["quote"] == "Nit only, otherwise fine."
            for quote in review_reports[0].behavioral_quotes
        )

    @pytest.mark.asyncio
    async def test_finalize_replaces_prior_writeback_for_same_cycle(self, session):
        db, mini_id = session
        external_id = "acme/widgets#789:allie:cafebabe"

        await upsert_review_cycle_prediction(
            db,
            mini_id,
            ReviewCyclePredictionUpsertRequest(
                external_id=external_id,
                source_type="github",
                metadata_json={"repo_full_name": "acme/widgets", "pr_number": 789},
                predicted_state=_review_state("Still blocked on tests.", "request_changes"),
            ),
        )

        await finalize_review_cycle(
            db,
            mini_id,
            ReviewCycleOutcomeUpdateRequest(
                external_id=external_id,
                source_type="github",
                human_review_outcome=_review_state("Need coverage before merge.", "request_changes"),
                delta_metrics={},
            ),
        )

        await finalize_review_cycle(
            db,
            mini_id,
            ReviewCycleOutcomeUpdateRequest(
                external_id=external_id,
                source_type="github",
                human_review_outcome=_review_state("Actually fine with a follow-up test.", "comment"),
                delta_metrics={},
            ),
        )

        findings_result = await db.execute(
            select(ExplorerFinding).where(
                ExplorerFinding.mini_id == mini_id,
                ExplorerFinding.source_type == "review_writeback",
            )
        )
        findings = findings_result.scalars().all()
        assert len(findings) == 1
        assert "actual approval_state=comment" in findings[0].content
        assert "Actually fine with a follow-up test." in findings[0].content

        quotes_result = await db.execute(
            select(ExplorerQuote).where(
                ExplorerQuote.mini_id == mini_id,
                ExplorerQuote.source_type == "review_writeback",
            )
        )
        quotes = quotes_result.scalars().all()
        assert len(quotes) == 1
        assert quotes[0].quote == "Actually fine with a follow-up test."
