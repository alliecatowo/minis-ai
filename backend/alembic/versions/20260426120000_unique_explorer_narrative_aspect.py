"""add unique constraint for explorer_narratives mini/aspect/source

Revision ID: 20260426120000
Revises: 20260426200000
Create Date: 2026-04-26 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260426120000"
down_revision: Union[str, None] = "20260426200000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_explorer_narrative_mini_aspect_source",
        "explorer_narratives",
        ["mini_id", "aspect", "explorer_source"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_explorer_narrative_mini_aspect_source",
        "explorer_narratives",
        type_="unique",
    )
