"""add review_cycles table for durable review prediction/outcome persistence

Revision ID: 20260422103000
Revises: 20260420210000
Create Date: 2026-04-22 10:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260422103000"
down_revision: Union[str, None] = "20260420210000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_cycles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "mini_id",
            sa.String(length=36),
            sa.ForeignKey("minis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_type",
            sa.String(length=50),
            nullable=False,
            server_default=sa.text("'github'"),
        ),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("predicted_state_json", sa.JSON(), nullable=False),
        sa.Column("human_review_outcome_json", sa.JSON(), nullable=True),
        sa.Column("delta_metrics_json", sa.JSON(), nullable=True),
        sa.Column("predicted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("human_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "mini_id",
            "source_type",
            "external_id",
            name="uq_review_cycles_mini_source_external_id",
        ),
    )
    op.create_index(op.f("ix_review_cycles_mini_id"), "review_cycles", ["mini_id"], unique=False)
    op.create_index(
        op.f("ix_review_cycles_source_type"), "review_cycles", ["source_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_review_cycles_source_type"), table_name="review_cycles")
    op.drop_index(op.f("ix_review_cycles_mini_id"), table_name="review_cycles")
    op.drop_table("review_cycles")
