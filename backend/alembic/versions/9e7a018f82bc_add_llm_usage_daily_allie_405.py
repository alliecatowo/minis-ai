"""add_llm_usage_daily_ALLIE_405

Revision ID: 9e7a018f82bc
Revises: 20260420101412
Create Date: 2026-04-20 14:43:22.597516

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9e7a018f82bc"
down_revision: Union[str, None] = "20260420101412"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_daily",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("model_tier", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("endpoint", sa.String(length=255), nullable=True),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day", "model_tier", "user_id", "endpoint", name="uq_llm_usage_daily"),
    )
    op.create_index("ix_llm_usage_daily_day", "llm_usage_daily", ["day"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_llm_usage_daily_day", table_name="llm_usage_daily")
    op.drop_table("llm_usage_daily")
