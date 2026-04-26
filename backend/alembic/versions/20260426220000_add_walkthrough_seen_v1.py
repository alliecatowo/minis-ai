"""add walkthrough seen v1 flag to user settings

Revision ID: 20260426220000
Revises: 20260426120000
Create Date: 2026-04-26 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260426220000"
down_revision: Union[str, None] = "20260426120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column(
            "walkthrough_seen_v1",
            sa.Boolean(),
            nullable=True,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "walkthrough_seen_v1")
