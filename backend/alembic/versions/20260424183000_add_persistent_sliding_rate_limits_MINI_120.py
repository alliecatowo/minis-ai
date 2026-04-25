"""add persistent sliding rate limits MINI-120

Revision ID: 20260424183000
Revises: 20260424120000
Create Date: 2026-04-24 18:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260424183000"
down_revision: Union[str, None] = "20260424120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sliding_rate_limit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sliding_rate_limit_events_key_created",
        "sliding_rate_limit_events",
        ["key_hash", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sliding_rate_limit_events_key_created",
        table_name="sliding_rate_limit_events",
    )
    op.drop_table("sliding_rate_limit_events")
