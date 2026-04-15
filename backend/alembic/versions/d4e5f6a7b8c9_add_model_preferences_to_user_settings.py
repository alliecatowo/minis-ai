"""add model_preferences to user_settings

Revision ID: d4e5f6a7b8c9
Revises: e5f6a7b8c9d0
Create Date: 2026-04-14 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user_settings',
        sa.Column('model_preferences', JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_settings', 'model_preferences')
