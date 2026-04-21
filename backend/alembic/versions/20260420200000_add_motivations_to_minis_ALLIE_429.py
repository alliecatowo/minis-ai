"""add motivations_json column to minis (ALLIE-429)

Revision ID: 20260420200000
Revises: ae757eba736d
Create Date: 2026-04-20 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "20260420200000"
down_revision: Union[str, None] = "ae757eba736d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "minis",
        sa.Column("motivations_json", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("minis", "motivations_json")
