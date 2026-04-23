"""add evidence_date column

Revision ID: d141d2a306d7
Revises: 20260422103000
Create Date: 2026-04-22 20:28:24.561217

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd141d2a306d7'
down_revision: Union[str, None] = '20260422103000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('evidence', sa.Column('evidence_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('evidence', 'evidence_date')
