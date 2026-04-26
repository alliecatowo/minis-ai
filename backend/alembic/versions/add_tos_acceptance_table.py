"""add tos_acceptance table

Revision ID: add_tos_acceptance_table
Revises: 20260426120000
Create Date: 2026-04-26 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "add_tos_acceptance_table"
down_revision: Union[str, None] = "20260426120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tos_acceptance",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tos_acceptance_user_id", "tos_acceptance", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tos_acceptance_user_id", table_name="tos_acceptance")
    op.drop_table("tos_acceptance")
