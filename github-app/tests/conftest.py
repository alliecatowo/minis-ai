from __future__ import annotations

import sys
from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


@pytest.fixture(autouse=True)
def _clear_review_sha_cache():
    """Clear the in-memory posted-SHA cache before each test for isolation."""
    import app.webhooks as wh

    wh._last_posted_sha_cache.clear()
    yield
    wh._last_posted_sha_cache.clear()
