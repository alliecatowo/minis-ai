"""add derived output JSON columns to minis (ALLIE-439)

Revision ID: 20260420112000
Revises: 20260420101412
Create Date: 2026-04-20 11:20:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260420112000"
down_revision: Union[str, None] = "20260420101412"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("minis", sa.Column("personality_typology_json", sa.JSON(), nullable=True))
    op.add_column("minis", sa.Column("behavioral_context_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("minis", "behavioral_context_json")
    op.drop_column("minis", "personality_typology_json")
