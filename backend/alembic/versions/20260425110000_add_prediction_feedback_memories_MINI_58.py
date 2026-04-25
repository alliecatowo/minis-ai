"""add prediction feedback memories table (MINI-58)

Revision ID: 20260425110000
Revises: 20260424120000
Create Date: 2026-04-25 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260425110000"
down_revision: Union[str, None] = "20260424120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prediction_feedback_memories",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "mini_id",
            sa.String(length=36),
            sa.ForeignKey("minis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cycle_type", sa.String(length=50), nullable=False),
        sa.Column("cycle_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("feedback_kind", sa.String(length=50), nullable=False),
        sa.Column("outcome_status", sa.String(length=50), nullable=False),
        sa.Column("delta_type", sa.String(length=50), nullable=False),
        sa.Column("issue_key", sa.String(length=255), nullable=True),
        sa.Column("predicted_private_assessment_json", sa.JSON(), nullable=True),
        sa.Column("predicted_expressed_feedback_json", sa.JSON(), nullable=True),
        sa.Column("actual_reviewer_behavior_json", sa.JSON(), nullable=True),
        sa.Column("raw_outcome_json", sa.JSON(), nullable=True),
        sa.Column("delta_json", sa.JSON(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        op.f("ix_prediction_feedback_memories_mini_id"),
        "prediction_feedback_memories",
        ["mini_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_feedback_memories_cycle_type"),
        "prediction_feedback_memories",
        ["cycle_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_feedback_memories_cycle_id"),
        "prediction_feedback_memories",
        ["cycle_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_feedback_memories_source_type"),
        "prediction_feedback_memories",
        ["source_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_feedback_memories_external_id"),
        "prediction_feedback_memories",
        ["external_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_feedback_memories_feedback_kind"),
        "prediction_feedback_memories",
        ["feedback_kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_feedback_memories_outcome_status"),
        "prediction_feedback_memories",
        ["outcome_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_feedback_memories_delta_type"),
        "prediction_feedback_memories",
        ["delta_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prediction_feedback_memories_issue_key"),
        "prediction_feedback_memories",
        ["issue_key"],
        unique=False,
    )
    op.create_index(
        "ix_prediction_feedback_memories_mini_created",
        "prediction_feedback_memories",
        ["mini_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_prediction_feedback_memories_cycle",
        "prediction_feedback_memories",
        ["cycle_type", "cycle_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_prediction_feedback_memories_cycle", table_name="prediction_feedback_memories")
    op.drop_index(
        "ix_prediction_feedback_memories_mini_created",
        table_name="prediction_feedback_memories",
    )
    op.drop_index(op.f("ix_prediction_feedback_memories_issue_key"), table_name="prediction_feedback_memories")
    op.drop_index(op.f("ix_prediction_feedback_memories_delta_type"), table_name="prediction_feedback_memories")
    op.drop_index(op.f("ix_prediction_feedback_memories_outcome_status"), table_name="prediction_feedback_memories")
    op.drop_index(op.f("ix_prediction_feedback_memories_feedback_kind"), table_name="prediction_feedback_memories")
    op.drop_index(op.f("ix_prediction_feedback_memories_external_id"), table_name="prediction_feedback_memories")
    op.drop_index(op.f("ix_prediction_feedback_memories_source_type"), table_name="prediction_feedback_memories")
    op.drop_index(op.f("ix_prediction_feedback_memories_cycle_id"), table_name="prediction_feedback_memories")
    op.drop_index(op.f("ix_prediction_feedback_memories_cycle_type"), table_name="prediction_feedback_memories")
    op.drop_index(op.f("ix_prediction_feedback_memories_mini_id"), table_name="prediction_feedback_memories")
    op.drop_table("prediction_feedback_memories")
