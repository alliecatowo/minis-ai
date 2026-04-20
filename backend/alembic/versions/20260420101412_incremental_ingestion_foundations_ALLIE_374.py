"""incremental ingestion foundations (ALLIE-374 M1)

Adds three new columns to the ``evidence`` table and one to
``explorer_progress``:

evidence:
  - external_id (VARCHAR 255, nullable, indexed)   — stable source-side key
  - last_fetched_at (TIMESTAMPTZ, nullable)         — most recent fetch timestamp
  - content_hash (VARCHAR 64, nullable)             — SHA-256 of content+metadata

explorer_progress:
  - last_explored_at (TIMESTAMPTZ, nullable)        — set when finish() is called

Also creates a partial unique index on (mini_id, source_type, external_id)
WHERE external_id IS NOT NULL.  This prevents duplicate inserts while allowing
legacy rows (external_id IS NULL) to coexist without any constraint violation.

Revision ID: 20260420101412
Revises: f6a7b8c9d0e1
Create Date: 2026-04-20 10:14:12.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "20260420101412"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── evidence: three new columns ────────────────────────────────────────
    op.add_column(
        "evidence",
        sa.Column("external_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_evidence_external_id",
        "evidence",
        ["external_id"],
    )
    op.add_column(
        "evidence",
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "evidence",
        sa.Column("content_hash", sa.String(64), nullable=True),
    )

    # Partial unique index: prevents duplicate inserts while allowing NULL
    # external_id rows (legacy data) to coexist without conflict.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_evidence_mini_source_external_id
        ON evidence (mini_id, source_type, external_id)
        WHERE external_id IS NOT NULL
        """
    )

    # ── explorer_progress: one new column ──────────────────────────────────
    op.add_column(
        "explorer_progress",
        sa.Column("last_explored_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # ── explorer_progress ──────────────────────────────────────────────────
    op.drop_column("explorer_progress", "last_explored_at")

    # ── evidence ───────────────────────────────────────────────────────────
    op.execute("DROP INDEX IF EXISTS uq_evidence_mini_source_external_id")
    op.drop_index("ix_evidence_external_id", table_name="evidence")
    op.drop_column("evidence", "content_hash")
    op.drop_column("evidence", "last_fetched_at")
    op.drop_column("evidence", "external_id")
