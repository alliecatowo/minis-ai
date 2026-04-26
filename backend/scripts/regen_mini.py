"""Regenerate a mini in-place by re-running the synthesis pipeline.

Usage: uv run python scripts/regen_mini.py <username>
Provider via DEFAULT_PROVIDER env var.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import select

from app.db import async_session
from app.models.mini import Mini
from app.plugins.loader import load_plugins
from app.synthesis.pipeline import run_pipeline_with_events

load_plugins()


async def main(username: str) -> int:
    async with async_session() as session:
        result = await session.execute(select(Mini).where(Mini.username == username))
        mini = result.scalars().first()
        if not mini:
            print(f"No mini found for {username}", file=sys.stderr)
            return 1
        owner_id = mini.owner_id
        mini_id = mini.id
        mini.status = "processing"
        await session.commit()

    print(f"Regenerating {username} (mini_id={mini_id}) with provider={os.environ.get('DEFAULT_PROVIDER', 'gemini')}")
    await run_pipeline_with_events(
        username,
        async_session,
        sources=["github", "claude_code"],
        owner_id=owner_id,
        mini_id=mini_id,
    )
    print("Pipeline complete.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: regen_mini.py <username>", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
