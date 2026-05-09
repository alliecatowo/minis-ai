#!/usr/bin/env python
"""Langfuse smoke test — verify tracing works end-to-end.

Usage:
    cd backend
    uv run python scripts/langfuse_smoke.py
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add backend to path so imports work from any working directory
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def main():
    """Send a test trace to Langfuse and print the dashboard URL."""
    from app.core.config import settings
    from app.core.feature_flags import FLAGS

    # Sync env var from settings (which reads from .env)
    os.environ["LANGFUSE_ENABLED"] = "true" if settings.langfuse_enabled else "false"

    # Verify Langfuse is enabled and configured
    if not FLAGS["LANGFUSE_ENABLED"].is_enabled():
        logger.error("LANGFUSE_ENABLED is not set. Cannot run smoke test.")
        return False

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.error("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required.")
        return False

    logger.info("Langfuse config detected:")
    logger.info(f"  Host: {settings.langfuse_host}")
    logger.info(f"  Public Key: {settings.langfuse_public_key[:20]}...")
    logger.info(f"  Secret Key: {settings.langfuse_secret_key[:20]}...")

    try:
        from langfuse import Langfuse

        # Create a client
        langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_host,
        )

        # Send a test trace using the modern API
        trace_id = langfuse.create_trace_id()
        trace_name = f"smoke-test-{datetime.now().isoformat()}"

        # Start an observation (span) at the trace level
        obs = langfuse.start_observation(
            trace_context={"trace_id": trace_id},
            name=trace_name,
            as_type="span",
            input={"test": "langfuse_smoke"},
            metadata={"environment": settings.environment},
        )

        # Update and end the observation
        obs.update(output={"message": "Langfuse smoke test successful"})
        obs.end()

        # Flush to ensure delivery
        langfuse.flush()

        # Construct trace URL manually
        trace_url = f"{settings.langfuse_host}/trace/{trace_id}"

        logger.info(f"✓ Trace sent successfully: {trace_name}")
        logger.info(f"✓ Trace ID: {trace_id}")
        logger.info("")
        logger.info("View your trace at:")
        logger.info(f"  {trace_url}")
        logger.info("")
        logger.info("Dashboard: https://us.cloud.langfuse.com")
        return True

    except Exception as e:
        logger.error(f"✗ Smoke test failed: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
