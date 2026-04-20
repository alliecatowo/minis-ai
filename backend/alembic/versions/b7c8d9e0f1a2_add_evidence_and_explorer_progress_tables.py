"""add evidence and explorer progress tables

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-14 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "mini_id",
            sa.String(36),
            sa.ForeignKey("minis.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_type", sa.String(50), nullable=False, index=True),
        sa.Column("item_type", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("explored", sa.Boolean(), server_default=sa.text("false"), index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "explorer_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "mini_id",
            sa.String(36),
            sa.ForeignKey("minis.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("0.5")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "explorer_quotes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "mini_id",
            sa.String(36),
            sa.ForeignKey("minis.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("significance", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "explorer_progress",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "mini_id",
            sa.String(36),
            sa.ForeignKey("minis.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("total_items", sa.Integer(), server_default=sa.text("0")),
        sa.Column("explored_items", sa.Integer(), server_default=sa.text("0")),
        sa.Column("findings_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("memories_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("quotes_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("nodes_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("explorer_progress")
    op.drop_table("explorer_quotes")
    op.drop_table("explorer_findings")
    op.drop_table("evidence")
