"""add username uniqueness constraint on users.github_username (ALLIE-377)

Adds a partial, case-insensitive unique index on users.github_username so that
duplicate rows (e.g. a stale public row + an owned row for the same handle)
cannot form going forward.

  CREATE UNIQUE INDEX uq_users_github_username_not_null
    ON users (LOWER(github_username))
    WHERE github_username IS NOT NULL;

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-04-19 21:27:20.000000

"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_users_github_username_not_null"


# ---------------------------------------------------------------------------
# Pre-flight duplicate check
# ---------------------------------------------------------------------------


def _check_no_duplicates(conn: sa.engine.Connection) -> None:
    """Raise if any duplicate LOWER(github_username) rows exist.

    If this raises, run the cleanup script first:
        backend/scripts/check_username_duplicates.py
    """
    result = conn.execute(
        sa.text(
            """
            SELECT LOWER(github_username) AS lower_username, COUNT(*) AS cnt
            FROM users
            WHERE github_username IS NOT NULL
            GROUP BY LOWER(github_username)
            HAVING COUNT(*) > 1
            """
        )
    )
    duplicates = result.fetchall()
    if duplicates:
        rows_str = ", ".join(f"{row[0]!r} ({row[1]} rows)" for row in duplicates)
        raise RuntimeError(
            f"Cannot add unique index: duplicate github_username values found: "
            f"{rows_str}. "
            f"Run `python backend/scripts/check_username_duplicates.py` to "
            f"identify and clean up duplicates before re-running this migration."
        )


# ---------------------------------------------------------------------------
# Upgrade / downgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()
    _check_no_duplicates(bind)

    # Drop the old non-partial unique constraint on github_username if it
    # exists (the initial schema created a plain UniqueConstraint; we replace
    # it with the partial, case-insensitive index below).
    # We use IF EXISTS via raw SQL so it's idempotent.
    bind.execute(sa.text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_github_username_key"))

    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX_NAME}
          ON users (LOWER(github_username))
          WHERE github_username IS NOT NULL
        """
    )
    logger.info("Created partial unique index %s on users(LOWER(github_username))", _INDEX_NAME)


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
    logger.info("Dropped index %s", _INDEX_NAME)
