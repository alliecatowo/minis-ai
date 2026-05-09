"""add append-only evidence supersession fields

Revision ID: 20260427090000
Revises: 658e5422d52b
Create Date: 2026-04-27 09:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260427090000"
down_revision: Union[str, None] = "658e5422d52b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("evidence", sa.Column("superseded_by_evidence_id", sa.String(length=36), nullable=True))
    op.add_column("evidence", sa.Column("supersession_reason_code", sa.String(length=64), nullable=True))
    op.add_column("evidence", sa.Column("supersession_reason_json", sa.JSON(), nullable=True))
    op.create_index("ix_evidence_superseded_at", "evidence", ["superseded_at"], unique=False)

    op.execute("DROP INDEX IF EXISTS uq_evidence_mini_source_external_id")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_evidence_mini_source_external_id
        ON evidence (mini_id, source_type, external_id)
        WHERE external_id IS NOT NULL AND superseded_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_evidence_mini_source_external_id")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_evidence_mini_source_external_id
        ON evidence (mini_id, source_type, external_id)
        WHERE external_id IS NOT NULL
        """
    )

    op.drop_index("ix_evidence_superseded_at", table_name="evidence")
    op.drop_column("evidence", "supersession_reason_json")
    op.drop_column("evidence", "supersession_reason_code")
    op.drop_column("evidence", "superseded_by_evidence_id")
    op.drop_column("evidence", "superseded_at")
