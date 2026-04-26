"""add last_pipeline_run_at to minis

Revision ID: 6b7c8d9e0f1a
Revises: 5402fa38b04f
Create Date: 2026-04-26 23:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b7c8d9e0f1a"
down_revision: Union[str, None] = "5402fa38b04f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("minis", sa.Column("last_pipeline_run_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("minis", "last_pipeline_run_at")
