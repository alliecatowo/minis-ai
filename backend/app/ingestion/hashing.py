"""Content hashing helpers for incremental ingestion (ALLIE-374 M1).

Provides a deterministic SHA-256 hash over evidence content + optional metadata
so the pipeline can detect when a previously-ingested item has changed on the
source side (mutation detection).
"""

from __future__ import annotations

import hashlib
import json


def hash_evidence_content(content: str, *, metadata: dict | None = None) -> str:
    """Return a SHA-256 hex digest over *content* and optional *metadata*.

    Rules:
    - *content* is stripped of leading/trailing whitespace before hashing so
      insignificant whitespace changes don't produce a different hash.
    - *metadata* keys are sorted (canonical JSON) so dict ordering is irrelevant.
    - If *metadata* is ``None`` or empty the hash is over content only.

    Args:
        content: The evidence content string.
        metadata: Optional supplementary key/value data (e.g. commit author,
            PR number).  Keys are sorted before serialisation.

    Returns:
        64-character lowercase hex digest.
    """
    hasher = hashlib.sha256()
    hasher.update(content.strip().encode())
    if metadata:
        canonical = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
        hasher.update(canonical.encode())
    return hasher.hexdigest()
