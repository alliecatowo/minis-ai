"""make explorer_source nullable on explorer_narratives

Revision ID: 20260426170000
Revises: 20260426110000
Create Date: 2026-04-26 17:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260426170000"
down_revision: Union[str, None] = "20260426110000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "explorer_narratives",
        "explorer_source",
        existing_type=sa.String(length=50),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "explorer_narratives",
        "explorer_source",
        existing_type=sa.String(length=50),
        nullable=False,
    )
