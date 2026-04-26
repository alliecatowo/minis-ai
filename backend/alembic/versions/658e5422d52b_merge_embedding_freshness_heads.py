"""merge embedding + freshness heads

Revision ID: 658e5422d52b
Revises: 20260426233000, 6b7c8d9e0f1a
Create Date: 2026-04-26 16:09:00.748870

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '658e5422d52b'
down_revision: Union[str, None] = ('20260426233000', '6b7c8d9e0f1a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
