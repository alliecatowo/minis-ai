"""drop NOT NULL on embeddings.embedding (legacy column, replaced by vector)

Revision ID: 20260509190000
Revises: 20260508120000
Create Date: 2026-05-09 19:00:00.000000

The embeddings table has both `embedding Vector(768)` (original, NOT NULL) and
`vector Vector(1536)` (added later for the new model). The pipeline writes only
to `vector`, leaving `embedding` NULL — which crashes on insert.

This migration drops the NOT NULL constraint so the legacy column can be left
empty while the new `vector` column carries the data.

"""
from typing import Sequence, Union


revision: str = '20260509190000'
down_revision: Union[str, None] = '20260508120000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from alembic import op
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding DROP NOT NULL")


def downgrade() -> None:
    from alembic import op
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding SET NOT NULL")
