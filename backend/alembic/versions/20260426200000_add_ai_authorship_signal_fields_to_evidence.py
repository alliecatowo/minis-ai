"""add ai authorship signal fields to evidence

Revision ID: 20260426200000
Revises: 20260426170000
Create Date: 2026-04-26 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260426200000"
down_revision: Union[str, None] = "20260426170000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("ai_authorship_likelihood", sa.Float(), nullable=True))
    op.add_column(
        "evidence",
        sa.Column("ai_style_markers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        op.f("ix_evidence_ai_authorship_likelihood"),
        "evidence",
        ["ai_authorship_likelihood"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_evidence_ai_authorship_likelihood"), table_name="evidence")
    op.drop_column("evidence", "ai_style_markers")
    op.drop_column("evidence", "ai_authorship_likelihood")
