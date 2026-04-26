"""merge tos and walkthrough heads

Revision ID: 5402fa38b04f
Revises: 20260426220000, add_tos_acceptance_table
Create Date: 2026-04-26 15:29:11.005754

"""
from typing import Sequence, Union



# revision identifiers, used by Alembic.
revision: str = '5402fa38b04f'
down_revision: Union[str, None] = ('20260426220000', 'add_tos_acceptance_table')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
