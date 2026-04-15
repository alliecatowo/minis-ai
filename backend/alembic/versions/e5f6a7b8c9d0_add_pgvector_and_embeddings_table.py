"""add pgvector extension and embeddings table

Revision ID: e5f6a7b8c9d0
Revises: c3d4e5f6a7b8
Create Date: 2026-04-14 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    op.create_table(
        'embeddings',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'mini_id',
            sa.String(36),
            sa.ForeignKey('minis.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
        ),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', Vector(768), nullable=False),
        sa.Column('source_type', sa.String(50), nullable=False, index=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # HNSW index for fast approximate nearest-neighbor search
    op.execute(
        'CREATE INDEX embeddings_embedding_hnsw_idx '
        'ON embeddings USING hnsw (embedding vector_cosine_ops)'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS embeddings_embedding_hnsw_idx')
    op.drop_table('embeddings')
