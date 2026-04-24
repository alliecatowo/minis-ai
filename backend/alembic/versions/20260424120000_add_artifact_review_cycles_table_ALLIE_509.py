"""add artifact_review_cycles table for design_doc / issue_plan prediction/outcome persistence (ALLIE-509)

Revision ID: 20260424120000
Revises: d141d2a306d7
Create Date: 2026-04-24 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260424120000"
down_revision: Union[str, None] = "d141d2a306d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artifact_review_cycles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "mini_id",
            sa.String(length=36),
            sa.ForeignKey("minis.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("predicted_state_json", sa.JSON(), nullable=False),
        sa.Column("human_outcome_json", sa.JSON(), nullable=True),
        sa.Column("delta_metrics_json", sa.JSON(), nullable=True),
        sa.Column("predicted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "mini_id",
            "artifact_type",
            "external_id",
            name="uq_artifact_review_cycles_mini_type_external_id",
        ),
    )
    op.create_index(
        op.f("ix_artifact_review_cycles_mini_id"),
        "artifact_review_cycles",
        ["mini_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_artifact_review_cycles_artifact_type"),
        "artifact_review_cycles",
        ["artifact_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_artifact_review_cycles_artifact_type"),
        table_name="artifact_review_cycles",
    )
    op.drop_index(
        op.f("ix_artifact_review_cycles_mini_id"),
        table_name="artifact_review_cycles",
    )
    op.drop_table("artifact_review_cycles")
