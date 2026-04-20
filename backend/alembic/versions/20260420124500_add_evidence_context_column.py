"""add bounded context tag to evidence

Adds an explicit ``context`` column to ``evidence`` so ingestion sources can
persist a bounded communication/content context for each raw evidence row.

Revision ID: 20260420124500
Revises: 20260420101412
Create Date: 2026-04-20 12:45:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260420124500"
down_revision: Union[str, None] = "20260420101412"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evidence",
        sa.Column("context", sa.String(length=64), nullable=False, server_default="general"),
    )
    op.create_index("ix_evidence_context", "evidence", ["context"])


def downgrade() -> None:
    op.drop_index("ix_evidence_context", table_name="evidence")
    op.drop_column("evidence", "context")
