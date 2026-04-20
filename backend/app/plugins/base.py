"""Base protocols for the Minis plugin system.

Ingestion sources fetch raw data from external services and format it as evidence
text for the LLM synthesis pipeline. Client plugins expose a mini through different
interfaces (web, MCP, CLI, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class IngestionResult:
    """Standard output from an ingestion source."""

    source_name: str
    identifier: str  # e.g. GitHub username, file path, Slack workspace
    evidence: str  # Formatted evidence text ready for LLM analysis
    raw_data: dict[str, Any] = field(default_factory=dict)  # Preserved for metadata
    stats: dict[str, Any] = field(default_factory=dict)  # Source-specific stats


@dataclass
class EvidenceItem:
    """Structured evidence item emitted by a source's fetch_items() method.

    Each item carries a stable external_id that enables idempotent upserts and
    incremental re-fetch — only new or mutated items need to be processed on
    subsequent pipeline runs.

    external_id formats (by source):
      - GitHub commits:        ``commit:{sha}``
      - GitHub PRs:            ``pr:{owner}/{repo}#{number}``
      - GitHub reviews:        ``review:{pr_id}#{review_id}``
      - GitHub issue comments: ``issue_comment:{id}``
      - Claude Code turns:     ``session:{session_uuid}#{turn_idx}``
    """

    external_id: str  # Stable identifier; unique within (mini_id, source_type)
    source_type: str  # Matches existing free-text source_type on Evidence rows
    item_type: str  # e.g. "commit", "pr", "review", "session"
    content: str
    metadata: dict | None = None
    privacy: Literal["public", "private"] = "public"


class IngestionSource(ABC):
    """Protocol for data ingestion sources.

    Each source knows how to fetch raw data from an external service and
    format it into evidence text suitable for personality analysis.
    """

    name: str  # Unique identifier, e.g. "github", "claude_code", "slack"
    source_type: str = "voice"  # "voice" or "memory"
    default_privacy: Literal["public", "private"] = "public"

    @abstractmethod
    async def fetch(self, identifier: str, **config: Any) -> IngestionResult:
        """Fetch data and return formatted evidence.

        Args:
            identifier: Source-specific identifier (username, file path, etc.)
            **config: Optional source-specific configuration.

        Returns:
            IngestionResult with formatted evidence text and metadata.
        """
        ...

    async def fetch_items(
        self,
        identifier: str,
        mini_id: str,
        session: Any,
        *,
        since_external_ids: set[str] | None = None,
    ) -> AsyncIterator[EvidenceItem]:
        """Yield structured EvidenceItem objects for this source.

        The default implementation falls back to the legacy ``fetch()`` path,
        wrapping the entire evidence string as a single item.  Sources that
        override this method emit one item per logical unit (commit, PR, session
        turn, etc.) with a stable ``external_id`` to enable incremental ingestion.

        Args:
            identifier: Source-specific identifier (username, path, etc.).
            mini_id: The mini being built.
            session: Active async SQLAlchemy session (may be None in tests).
            since_external_ids: Set of external_ids already stored for this
                mini+source.  Sources should skip items whose external_id is
                already present (no-change fast path).

        Yields:
            EvidenceItem objects ready to be upserted into the Evidence table.
        """
        # Default: wrap the legacy fetch() output as a single unkeyed item.
        # Sources that override this method bypass this fallback entirely.
        result = await self.fetch(identifier, mini_id=mini_id, session=session)
        if result.evidence:
            yield EvidenceItem(
                external_id=f"legacy:{self.name}:{identifier}",
                source_type=self.name,
                item_type="bulk",
                content=result.evidence,
                privacy=getattr(self, "default_privacy", "public"),
            )


class ClientPlugin(ABC):
    """Protocol for output client plugins.

    Each client exposes a mini's personality through a different interface.
    Clients are registered at startup and may add routes, start servers, etc.
    """

    name: str  # Unique identifier, e.g. "web", "mcp", "cli"

    @abstractmethod
    async def setup(self, app: Any) -> None:
        """Initialize the client plugin. Called during app startup.

        Args:
            app: The FastAPI application instance (or None for standalone clients).
        """
        ...
