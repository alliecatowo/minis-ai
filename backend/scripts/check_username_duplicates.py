#!/usr/bin/env python3
"""Pre-flight duplicate check for ALLIE-377 migration.

Usage:
    cd backend
    uv run python scripts/check_username_duplicates.py

Exits 0 if no duplicates are found (safe to run migration).
Exits 1 if duplicates exist (clean them up first).
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

# Ensure the app package is importable when run from the backend/ directory.
sys.path.insert(0, ".")


async def main() -> int:
    from app.db import async_session

    async with async_session() as session:
        result = await session.execute(
            text(
                """
                SELECT LOWER(github_username) AS lower_username,
                       array_agg(id ORDER BY created_at) AS ids,
                       COUNT(*) AS cnt
                FROM users
                WHERE github_username IS NOT NULL
                GROUP BY LOWER(github_username)
                HAVING COUNT(*) > 1
                ORDER BY lower_username
                """
            )
        )
        rows = result.fetchall()

    if not rows:
        print("OK — no duplicate github_username values found. Safe to run migration.")
        return 0

    print(
        f"ERROR — found {len(rows)} duplicate github_username group(s):\n",
        file=sys.stderr,
    )
    for row in rows:
        print(
            f"  username={row[0]!r}  count={row[2]}  user_ids={row[1]}",
            file=sys.stderr,
        )

    print(
        "\nResolve duplicates (reassign or delete stale rows) before running the migration.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
