"""Integration tests for durable review-cycle persistence."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.evidence import ReviewCycle
from app.models.schemas import (
    ReviewCycleOutcomeUpdateRequest,
    ReviewCyclePredictionUpsertRequest,
    StructuredReviewState,
)
from app.review_cycles import finalize_review_cycle, upsert_review_cycle_prediction

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
    yield
    async with engine.begin() as conn:
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
                    "approval_state_changed": True,
                    "predicted_blockers": 1,
                    "actual_blockers": 0,
                    "matched_blockers": 0,
                },
            ),
        )

        assert finalized is not None
        assert finalized.id == created.id
        assert finalized.human_review_outcome["expressed_feedback"]["approval_state"] == "comment"
        assert finalized.delta_metrics["approval_state_changed"] is True
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
