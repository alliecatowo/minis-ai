"""add embeddings vector retrieval columns

Revision ID: 20260426233000
Revises: 5402fa38b04f
Create Date: 2026-04-26 23:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260426233000"
down_revision: Union[str, None] = "5402fa38b04f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column("embeddings", sa.Column("table_name", sa.String(length=64), nullable=True))
    op.add_column("embeddings", sa.Column("row_id", sa.String(length=36), nullable=True))
    op.add_column("embeddings", sa.Column("chunk_index", sa.Integer(), nullable=True))
    op.execute("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS vector vector(1536)")

    op.create_index("ix_embeddings_table_name", "embeddings", ["table_name"], unique=False)
    op.create_index("ix_embeddings_row_id", "embeddings", ["row_id"], unique=False)
    op.create_index("ix_embeddings_chunk_index", "embeddings", ["chunk_index"], unique=False)
    op.create_index(
        "ix_embeddings_mini_table_name",
        "embeddings",
        ["mini_id", "table_name"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_embeddings_table_row_chunk",
        "embeddings",
        ["table_name", "row_id", "chunk_index"],
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS embeddings_vector_hnsw_idx "
        "ON embeddings USING hnsw (vector vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS embeddings_vector_hnsw_idx")
    op.drop_constraint("uq_embeddings_table_row_chunk", "embeddings", type_="unique")
    op.drop_index("ix_embeddings_mini_table_name", table_name="embeddings")
    op.drop_index("ix_embeddings_chunk_index", table_name="embeddings")
    op.drop_index("ix_embeddings_row_id", table_name="embeddings")
    op.drop_index("ix_embeddings_table_name", table_name="embeddings")

    op.execute("ALTER TABLE embeddings DROP COLUMN IF EXISTS vector")
    op.drop_column("embeddings", "chunk_index")
    op.drop_column("embeddings", "row_id")
    op.drop_column("embeddings", "table_name")
