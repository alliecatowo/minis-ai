"""add evidence envelope fields for review-grade provenance (MINI-218)

Revision ID: 20260424153000
Revises: 20260424120000
Create Date: 2026-04-24 15:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260424153000"
down_revision: Union[str, None] = "20260424120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("source_uri", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("author_id", sa.String(length=255), nullable=True))
    op.add_column("evidence", sa.Column("audience_id", sa.String(length=255), nullable=True))
    op.add_column("evidence", sa.Column("target_id", sa.String(length=255), nullable=True))
    op.add_column("evidence", sa.Column("scope_json", sa.JSON(), nullable=True))
    op.add_column("evidence", sa.Column("raw_body", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("raw_body_ref", sa.Text(), nullable=True))
    op.add_column("evidence", sa.Column("raw_context_json", sa.JSON(), nullable=True))
    op.add_column("evidence", sa.Column("provenance_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence", "provenance_json")
    op.drop_column("evidence", "raw_context_json")
    op.drop_column("evidence", "raw_body_ref")
    op.drop_column("evidence", "raw_body")
    op.drop_column("evidence", "scope_json")
    op.drop_column("evidence", "target_id")
    op.drop_column("evidence", "audience_id")
    op.drop_column("evidence", "author_id")
    op.drop_column("evidence", "source_uri")
