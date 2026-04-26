"""phase 2 schemas narratives evidence_ids register quotes reasoning edges

Revision ID: 20260426110000
Revises: 20260425110000
Create Date: 2026-04-26 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260426110000"
down_revision: Union[str, None] = "20260425110000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "explorer_narratives",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mini_id", sa.String(length=36), nullable=False),
        sa.Column("explorer_source", sa.String(length=50), nullable=False),
        sa.Column("aspect", sa.String(length=64), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["mini_id"], ["minis.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_explorer_narratives_mini_aspect_created",
        "explorer_narratives",
        ["mini_id", "aspect", "created_at"],
        unique=False,
    )

    op.add_column(
        "explorer_quotes",
        sa.Column("register_level", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("explorer_quotes", "register_level")
    op.drop_index("ix_explorer_narratives_mini_aspect_created", table_name="explorer_narratives")
    op.drop_table("explorer_narratives")
