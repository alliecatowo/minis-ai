"""Pipeline orchestration: FETCH → EXPLORE → SYNTHESIZE with SSE progress.

Three stages:
1. FETCH — Ingest raw data from sources, store as Evidence DB records
2. EXPLORE — Parallel PydanticAI agents analyze evidence via tools.py
3. SYNTHESIZE — Chief synthesizer crafts soul document from DB findings
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy import select

from app.models.evidence import Evidence, ExplorerProgress
from app.models.mini import Mini
from app.models.schemas import PipelineEvent
from app.plugins.base import IngestionResult
from app.plugins.registry import registry
from app.synthesis.explorers import get_explorer
from app.synthesis.explorers.base import ExplorerReport
from app.synthesis.spirit import build_system_prompt

# Chief synthesizer — DB-driven version is preferred; legacy fallback for tests
try:
    from app.synthesis.chief import run_chief_synthesizer, run_chief_synthesis
except ImportError:  # pragma: no cover
    async def run_chief_synthesizer(mini_id, db_session, **kwargs):  # type: ignore[misc]
        raise NotImplementedError("Chief synthesizer not available")

    async def run_chief_synthesis(username, reports, **kwargs):  # type: ignore[misc]
        raise NotImplementedError("Chief synthesizer not available")

# Import explorer modules to trigger registration
import app.synthesis.explorers.github_explorer  # noqa: F401
import app.synthesis.explorers.claude_code_explorer  # noqa: F401
import app.synthesis.explorers.blog_explorer  # noqa: F401
import app.synthesis.explorers.hackernews_explorer  # noqa: F401
import app.synthesis.explorers.stackoverflow_explorer  # noqa: F401
import app.synthesis.explorers.devto_explorer  # noqa: F401
import app.synthesis.explorers.website_explorer  # noqa: F401

logger = logging.getLogger(__name__)

# Type alias for progress callbacks
ProgressCallback = Callable[[PipelineEvent], Coroutine[Any, Any, None]]

# ---------------------------------------------------------------------------
# Defensive imports for the embeddings module (built by a parallel agent).
# If the module isn't available yet, _EMBEDDINGS_AVAILABLE stays False and
# embedding generation is silently skipped.
# ---------------------------------------------------------------------------
_EMBEDDINGS_AVAILABLE = False
try:
    from app.core.embeddings import embed_texts  # type: ignore[import]
    from app.models.embeddings import Embedding  # type: ignore[import]
    _EMBEDDINGS_AVAILABLE = True
except ImportError:
    logger.debug("Embeddings module not available; skipping embedding generation")


def _chunk_text(text: str, chunk_size: int = 500) -> list[str]:
    """Split *text* into chunks of at most *chunk_size* characters.

    Tries to split on paragraph boundaries first, then sentence boundaries,
    then hard-cuts at *chunk_size*.
    """
    if not text:
        return []
    # Split on double-newlines (paragraphs) first
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        if current_len + len(para) > chunk_size and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        # If a single paragraph exceeds chunk_size, hard-split it
        if len(para) > chunk_size:
            for i in range(0, len(para), chunk_size):
                chunks.append(para[i : i + chunk_size])
        else:
            current.append(para)
            current_len += len(para)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


async def _generate_embeddings(
    mini_id: str,
    memory_content: str,
    evidence_cache: str,
    knowledge_graph_json: dict | None,
    session_factory: Any,
) -> None:
    """Generate and persist embeddings for a mini after the SAVE stage.

    This function never raises — any failure is logged as a warning so it
    cannot block pipeline completion.
    """
    if not _EMBEDDINGS_AVAILABLE:
        return
    try:
        chunks_with_type: list[tuple[str, str]] = []

        # Memory chunks
        for chunk in _chunk_text(memory_content or ""):
            chunks_with_type.append((chunk, "memory"))

        # Evidence chunks
        for chunk in _chunk_text(evidence_cache or ""):
            chunks_with_type.append((chunk, "evidence"))

        # Knowledge graph node descriptions
        if knowledge_graph_json:
            nodes = knowledge_graph_json.get("nodes", [])
            for node in nodes:
                description = node.get("description") or node.get("name") or ""
                if description.strip():
                    chunks_with_type.append((description.strip(), "knowledge_node"))

        if not chunks_with_type:
            return

        texts = [c for c, _ in chunks_with_type]
        source_types = [t for _, t in chunks_with_type]

        # Embed all texts in one call (implementation may batch internally)
        vectors = await embed_texts(texts)

        async with session_factory() as session:
            async with session.begin():
                # Delete existing embeddings for this mini (re-train scenario)
                from sqlalchemy import delete as sa_delete
                await session.execute(
                    sa_delete(Embedding).where(Embedding.mini_id == mini_id)
                )
                for text, source_type, vector in zip(texts, source_types, vectors):
                    session.add(
                        Embedding(
                            mini_id=mini_id,
                            source_type=source_type,
                            content=text,
                            embedding=vector,
                        )
                    )

        logger.info(
            "Stored %d embeddings for mini %s (%s memory, %s evidence, %s kg)",
            len(chunks_with_type),
            mini_id,
            sum(1 for _, t in chunks_with_type if t == "memory"),
            sum(1 for _, t in chunks_with_type if t == "evidence"),
            sum(1 for _, t in chunks_with_type if t == "knowledge_node"),
        )

    except Exception:
        logger.warning(
            "Embedding generation failed for mini %s — continuing without embeddings",
            mini_id,
            exc_info=True,
        )


def _split_evidence_into_items(
    evidence_text: str,
    source_name: str,
) -> list[dict[str, Any]]:
    """Split formatted evidence text into individual DB-storable items.

    Tries to split on section boundaries (``---``, ``## ``, numbered items).
    Returns a list of dicts with ``type``, ``content``, and optional ``metadata``.
    """
    if not evidence_text or not evidence_text.strip():
        return []

    # Strategy 1: split on horizontal rules (``---`` or ``===`` on their own line)
    hr_pattern = re.compile(r"^(?:-{3,}|={3,})\s*$", re.MULTILINE)
    sections = [s.strip() for s in hr_pattern.split(evidence_text) if s.strip()]

    # Strategy 2: if that yielded only one chunk, split on markdown H2 headings
    if len(sections) <= 1:
        sections = [s.strip() for s in re.split(r"(?m)^## ", evidence_text) if s.strip()]
        # Re-attach the stripped heading marker
        sections = [f"## {s}" if not s.startswith("#") else s for s in sections]

    # Strategy 3: if still only one chunk, split on numbered items (1. ... 2. ...)
    if len(sections) <= 1 and evidence_text:
        sections = [s.strip() for s in re.split(r"(?m)^\d+\.\s+", evidence_text) if s.strip()]

    # Fallback: single item
    if not sections:
        sections = [evidence_text.strip()]

    items: list[dict[str, Any]] = []
    for section in sections:
        if not section.strip():
            continue
        # Infer item_type from content heuristics
        lower = section.lower()
        if any(k in lower for k in ("commit", "diff", "patch", "+++", "---")):
            item_type = "commit"
        elif any(k in lower for k in ("pull request", "pr #", "review", "comment")):
            item_type = "pr_review"
        elif any(k in lower for k in ("blog", "post", "article", "published")):
            item_type = "blog_post"
        elif any(k in lower for k in ("issue", "bug", "feature request")):
            item_type = "issue"
        elif any(k in lower for k in ("readme", "documentation", "doc")):
            item_type = "documentation"
        elif source_name in ("hackernews", "stackoverflow"):
            item_type = "comment"
        else:
            item_type = "general"

        items.append({"type": item_type, "content": section})

    return items


async def _store_evidence_in_db(
    mini_id: str,
    source_name: str,
    evidence_text: str,
    session_factory: Any,
) -> int:
    """Parse evidence text and persist items + progress record to the DB.

    Returns the number of evidence items stored.
    """
    items = _split_evidence_into_items(evidence_text, source_name)

    async with session_factory() as session:
        async with session.begin():
            for item in items:
                ev = Evidence(
                    mini_id=mini_id,
                    source_type=source_name,
                    item_type=item["type"],
                    content=item["content"],
                    metadata_json=item.get("metadata"),
                )
                session.add(ev)

            # Upsert ExplorerProgress — replace if exists from a previous run
            prog = ExplorerProgress(
                mini_id=mini_id,
                source_type=source_name,
                total_items=len(items),
                status="pending",
            )
            session.add(prog)

    return len(items)


async def _build_structured_from_db(
    mini_id: str,
    session_factory: Any,
) -> tuple[dict, dict]:
    """Reconstruct knowledge graph and principles dicts from DB findings.

    Returns (kg_json, principles_json) dicts compatible with the Mini model.
    """
    from app.models.evidence import ExplorerFinding
    from app.models.knowledge import (
        KnowledgeEdge,
        KnowledgeGraph,
        KnowledgeNode,
        NodeType,
        Principle,
        PrinciplesMatrix,
        RelationType,
    )

    kg = KnowledgeGraph()
    pm = PrinciplesMatrix()

    async with session_factory() as session:
        stmt = select(ExplorerFinding).where(
            ExplorerFinding.mini_id == mini_id,
            ExplorerFinding.category.in_(["knowledge_node", "knowledge_edge", "principle"]),
        )
        rows = await session.execute(stmt)
        findings = rows.scalars().all()

    for f in findings:
        try:
            data = json.loads(f.content)
        except (json.JSONDecodeError, TypeError):
            continue

        if f.category == "knowledge_node":
            try:
                node = KnowledgeNode(
                    id=data.get("name", "").lower().replace(" ", "-"),
                    name=data.get("name", ""),
                    type=NodeType(data.get("type", "skill")),
                    depth=data.get("depth", 0.5),
                    confidence=data.get("confidence", 0.5),
                )
                kg.nodes.append(node)
            except Exception:
                pass
        elif f.category == "knowledge_edge":
            try:
                edge = KnowledgeEdge(
                    source=data.get("source", ""),
                    target=data.get("target", ""),
                    relation=RelationType(data.get("relation", "related_to")),
                    weight=data.get("weight", 0.5),
                )
                kg.edges.append(edge)
            except Exception:
                pass
        elif f.category == "principle":
            try:
                p = Principle(
                    trigger=data.get("trigger", ""),
                    action=data.get("action", ""),
                    value=data.get("value", ""),
                    intensity=float(data.get("intensity", 5)) / 10.0,
                )
                pm.principles.append(p)
            except Exception:
                pass

    return kg.model_dump(mode="json"), pm.model_dump(mode="json")


async def _build_synthetic_reports_from_db(
    mini_id: str,
    session_factory: Any,
) -> list["ExplorerReport"]:
    """Build minimal ExplorerReport objects from DB findings for LLM extraction.

    Used so that extract_roles_llm / extract_skills_llm / extract_traits_llm
    (which expect ExplorerReport lists) can process DB-persisted findings.
    """
    from app.models.evidence import ExplorerFinding
    from app.synthesis.explorers.base import ExplorerReport, MemoryEntry

    async with session_factory() as session:
        stmt = select(ExplorerFinding).where(
            ExplorerFinding.mini_id == mini_id,
        )
        rows = await session.execute(stmt)
        findings = rows.scalars().all()

    if not findings:
        return []

    # Group by source_type
    by_source: dict[str, list] = {}
    for f in findings:
        by_source.setdefault(f.source_type, []).append(f)

    reports: list[ExplorerReport] = []
    for source_type, source_findings in by_source.items():
        personality_parts: list[str] = []
        memory_entries: list[MemoryEntry] = []

        for f in source_findings:
            if f.category.startswith("memory:"):
                try:
                    data = json.loads(f.content)
                    text = data.get("text", f.content)
                    cat = f.category.replace("memory:", "")
                    memory_entries.append(
                        MemoryEntry(
                            category=cat,
                            topic="",
                            content=text,
                            confidence=f.confidence,
                            source_type=source_type,
                        )
                    )
                except (json.JSONDecodeError, TypeError):
                    memory_entries.append(
                        MemoryEntry(
                            category=f.category,
                            topic="",
                            content=f.content,
                            confidence=f.confidence,
                            source_type=source_type,
                        )
                    )
            elif f.category in ("knowledge_node", "knowledge_edge", "principle"):
                # These are handled separately in _build_structured_from_db
                pass
            else:
                personality_parts.append(f"[{f.category}] {f.content}")

        reports.append(
            ExplorerReport(
                source_name=source_type,
                personality_findings="\n\n".join(personality_parts),
                memory_entries=memory_entries,
                confidence_summary=f"DB-backed: {len(source_findings)} findings",
            )
        )

    return reports


async def _noop_callback(event: PipelineEvent) -> None:
    pass


async def run_pipeline(
    username: str,
    session_factory: Any,
    on_progress: ProgressCallback | None = None,
    sources: list[str] | None = None,
    owner_id: str | None = None,
    mini_id: str | None = None,
    source_identifiers: dict[str, str] | None = None,
) -> None:
    """Run the full mini creation pipeline.

    Stages:
    1. FETCH — get data from ingestion sources
    2. EXPLORE — launch explorer agents per source in parallel
    3. SYNTHESIZE — chief synthesizer crafts soul document + save

    Args:
        username: Primary identifier (GitHub username, etc.) to create a mini for.
        session_factory: Async session factory for database access.
        on_progress: Optional async callback for pipeline progress events.
        sources: List of ingestion source names to use. Defaults to ["github"].
        owner_id: Optional owner ID for user-specific data directories.
        mini_id: The database ID of the Mini record to update.
        source_identifiers: Per-source identifiers (e.g. {"hackernews": "pg"}).
    """
    emit = on_progress or _noop_callback

    # ── Source expansion ─────────────────────────────────────────────
    # Always start with github; supplement with other available sources.
    # Any caller-provided list is honoured as-is; when the default ["github"]
    # is used we try to opportunistically add hackernews/stackoverflow using
    # the same username (both have graceful not-found handling).
    source_names = list(sources or ["github"])
    # Sources are explicitly selected by the user via source_identifiers.
    # Do NOT auto-add sources by username matching — users may not have
    # accounts on other platforms, or may use different usernames.

    # ── Langfuse tracing (no-op when disabled) ────────────────────────
    trace = None
    langfuse_client = None
    try:
        from app.core.config import settings as _settings
        if _settings.langfuse_enabled:
            from langfuse import Langfuse
            langfuse_client = Langfuse()
            trace = langfuse_client.trace(
                name="mini_creation_pipeline",
                user_id=username,
                metadata={"sources": source_names, "mini_id": mini_id},
            )
    except Exception:
        logger.debug("Langfuse tracing unavailable, continuing without it")
        trace = None

    try:
        # ── Stage 1: FETCH ───────────────────────────────────────────────
        if trace:
            fetch_span = trace.span(name="fetch", metadata={"sources": source_names})
        await emit(PipelineEvent(
            stage="fetch", status="started",
            message=f"Fetching data from {', '.join(source_names)}...",
            progress=0.0,
        ))

        results: list[IngestionResult] = []
        all_stats: dict[str, Any] = {}

        # Load excluded repos for this mini
        excluded_repos: set[str] = set()
        if mini_id is not None:
            from app.models.ingestion_data import MiniRepoConfig

            async with session_factory() as _cfg_session:
                cfg_result = await _cfg_session.execute(
                    select(MiniRepoConfig).where(
                        MiniRepoConfig.mini_id == mini_id,
                        MiniRepoConfig.included == False,  # noqa: E712
                    )
                )
                excluded_repos = {c.repo_full_name for c in cfg_result.scalars().all()}

        for i, source_name in enumerate(source_names):
            try:
                source = registry.get_source(source_name)
            except KeyError:
                logger.warning("Unknown source: %s, skipping", source_name)
                continue

            # Use per-source identifier if provided, otherwise fall back to username
            identifier = username
            if source_identifiers:
                identifier = source_identifiers.get(source_name, username)

            # Build kwargs — pass mini_id + session for caching when available
            fetch_kwargs: dict[str, Any] = {}
            if mini_id is not None:
                fetch_kwargs["mini_id"] = mini_id
            if source_name == "claude_code" and owner_id is not None:
                fetch_kwargs["data_dir"] = f"data/uploads/{owner_id}/claude_code"

            # Use a dedicated session for sources that support caching
            try:
                if mini_id is not None:
                    async with session_factory() as fetch_session:
                        async with fetch_session.begin():
                            fetch_kwargs["session"] = fetch_session
                            result = await source.fetch(identifier, **fetch_kwargs)
                else:
                    result = await source.fetch(identifier, **fetch_kwargs)

                results.append(result)
                all_stats[source_name] = result.stats
            except Exception as e:
                logger.warning("Source '%s' failed for %s: %s — skipping", source_name, identifier, e)
                continue

            # ── Store evidence as DB records ─────────────────────────────
            if mini_id is not None and result.evidence:
                try:
                    n_items = await _store_evidence_in_db(
                        mini_id=mini_id,
                        source_name=source_name,
                        evidence_text=result.evidence,
                        session_factory=session_factory,
                    )
                    logger.info(
                        "Stored %d evidence items for source '%s' (mini %s)",
                        n_items, source_name, mini_id,
                    )
                except Exception:
                    logger.warning(
                        "Failed to store evidence for source '%s', continuing",
                        source_name,
                        exc_info=True,
                    )

            progress = 0.05 + (0.15 * (i + 1) / len(source_names))
            await emit(PipelineEvent(
                stage="fetch", status="completed",
                message=f"Fetched data from {source_name}",
                progress=progress,
            ))

        if not results:
            raise ValueError(f"No data fetched from any source: {source_names}")

        # Filter out excluded repos from evidence
        if excluded_repos:
            for r in results:
                if r.source_name == "github" and r.raw_data.get("repos_summary"):
                    r.raw_data["repos_summary"]["top_repos"] = [
                        repo for repo in r.raw_data["repos_summary"].get("top_repos", [])
                        if repo.get("full_name") not in excluded_repos
                    ]

        # Cache evidence for chat tools
        evidence_cache = "\n\n---\n\n".join(r.evidence for r in results if r.evidence)

        if trace:
            fetch_span.end()

        # ── Stage 2: EXPLORE ─────────────────────────────────────────────
        if trace:
            explore_span = trace.span(name="explore", metadata={"explorer_count": len(results)})
        await emit(PipelineEvent(
            stage="explore", status="started",
            message=f"Launching {len(results)} explorer agent(s)...",
            progress=0.2,
        ))

        explorer_tasks = []
        explorer_source_names = []
        # Track configured explorers so we can close their sessions after the
        # parallel gather completes.
        configured_explorers: list[Any] = []

        for ingestion_result in results:
            source_name = ingestion_result.source_name
            try:
                explorer = get_explorer(source_name)
            except KeyError:
                logger.warning(
                    "No explorer registered for source '%s', skipping exploration",
                    source_name,
                )
                continue

            # Inject DB context so the explorer uses the full 12-tool DB suite
            if mini_id is not None:
                # Each explorer gets its own session to allow parallel execution
                explore_session = session_factory()
                explorer._db_session = await explore_session.__aenter__()
                explorer._mini_id = mini_id
                explorer._explore_session_ctx = explore_session
            else:
                explorer._db_session = None
                explorer._mini_id = None
                explorer._explore_session_ctx = None

            configured_explorers.append(explorer)
            explorer_tasks.append(
                explorer.explore(
                    username,
                    ingestion_result.evidence,
                    ingestion_result.raw_data,
                )
            )
            explorer_source_names.append(source_name)

        # Run all explorers in parallel
        explorer_reports: list[ExplorerReport] = []
        if explorer_tasks:
            completed = await asyncio.gather(*explorer_tasks, return_exceptions=True)
            for i, result_or_exc in enumerate(completed):
                if isinstance(result_or_exc, Exception):
                    logger.error(
                        "Explorer '%s' failed: %s",
                        explorer_source_names[i],
                        result_or_exc,
                    )
                else:
                    explorer_reports.append(result_or_exc)

        # Close all explorer sessions using the tracked instances
        for exp in configured_explorers:
            ctx = getattr(exp, "_explore_session_ctx", None)
            if ctx is not None:
                try:
                    await ctx.__aexit__(None, None, None)
                except Exception:
                    logger.debug("Error closing explorer session: %s", exp, exc_info=True)
                exp._explore_session_ctx = None
                exp._db_session = None

        await emit(PipelineEvent(
            stage="explore", status="completed",
            message=f"Exploration complete: {len(explorer_reports)} report(s) from "
                    f"{', '.join(r.source_name for r in explorer_reports)}",
            progress=0.5,
        ))

        if not explorer_reports:
            raise ValueError("No explorer reports produced — cannot synthesize")

        if trace:
            explore_span.end()

        # ── Stage 3: SYNTHESIZE + SAVE ───────────────────────────────────
        if trace:
            synthesize_span = trace.span(name="synthesize")
        await emit(PipelineEvent(
            stage="synthesize", status="started",
            message="Chief synthesizer crafting soul document...",
            progress=0.55,
        ))

        # ── Use DB-driven synthesizer when mini_id is available ──────────
        if mini_id is not None:
            # DB path: run_chief_synthesizer reads directly from ExplorerFinding /
            # ExplorerQuote tables populated by the explorer agents above.
            async with session_factory() as synth_session:
                spirit_content = await run_chief_synthesizer(
                    mini_id=mini_id,
                    db_session=synth_session,
                )

            # Build memory content from DB findings (memory:* category)
            from app.models.evidence import ExplorerFinding as _EF
            from sqlalchemy import select as _select

            memory_parts: list[str] = []
            async with session_factory() as mem_session:
                mem_stmt = (
                    _select(_EF)
                    .where(
                        _EF.mini_id == mini_id,
                        _EF.category.like("memory:%"),
                    )
                    .order_by(_EF.confidence.desc())
                )
                mem_rows = await mem_session.execute(mem_stmt)
                for finding in mem_rows.scalars().all():
                    try:
                        data = json.loads(finding.content)
                        text = data.get("text", finding.content)
                        ctx = data.get("context_type", finding.category)
                        memory_parts.append(f"[{ctx}] {text}")
                    except (json.JSONDecodeError, TypeError):
                        memory_parts.append(finding.content)

            # Also collect from in-memory report entries (fallback / supplemental)
            for report in explorer_reports:
                for entry in report.memory_entries:
                    memory_parts.append(f"[{entry.category}/{entry.topic}] {entry.content}")

            memory_content = "\n".join(memory_parts)

        else:
            # Legacy path (tests / no DB): pass explorer reports as text blobs
            all_context_evidence: dict[str, list[str]] = {}
            for report in explorer_reports:
                for ctx_key, ctx_quotes in report.context_evidence.items():
                    all_context_evidence.setdefault(ctx_key, []).extend(ctx_quotes)

            spirit_content = await run_chief_synthesis(
                username, explorer_reports,
                context_evidence=all_context_evidence if all_context_evidence else None,
            )

            memory_parts = []
            for report in explorer_reports:
                for entry in report.memory_entries:
                    memory_parts.append(f"[{entry.category}/{entry.topic}] {entry.content}")
            memory_content = "\n".join(memory_parts)

        # Extract profile info from the first source that has it (prefer github)
        display_name = username
        bio = ""
        avatar_url = ""
        for r in results:
            profile = r.raw_data.get("profile", {})
            if profile:
                display_name = profile.get("name") or display_name
                bio = profile.get("bio") or bio
                avatar_url = profile.get("avatar_url") or avatar_url
                break

        system_prompt = build_system_prompt(username, spirit_content, memory_content)

        await emit(PipelineEvent(
            stage="synthesize", status="completed",
            message="Soul document generated",
            progress=0.9,
        ))

        if trace:
            synthesize_span.end()

        # ── SAVE ─────────────────────────────────────────────────────────
        if trace:
            save_span = trace.span(name="save")
        await emit(PipelineEvent(
            stage="save", status="started",
            message="Saving mini...", progress=0.9,
        ))

        # Extract structured data from DB findings (DB path) or explorer reports
        # (legacy path).
        from app.synthesis.memory_assembler import (
            _merge_knowledge_graphs,
            _merge_principles,
            extract_roles_llm,
            extract_skills_llm,
            extract_traits_llm,
            extract_values_json,
        )

        if mini_id is not None:
            # DB path: reconstruct KG and principles from stored findings
            kg_json, principles_json = await _build_structured_from_db(
                mini_id=mini_id,
                session_factory=session_factory,
            )
            # For roles/skills/traits, pass DB findings as synthetic reports
            db_reports = await _build_synthetic_reports_from_db(
                mini_id=mini_id,
                session_factory=session_factory,
            )
            reports_for_extraction = db_reports if db_reports else explorer_reports
        else:
            reports_for_extraction = explorer_reports
            merged_kg = _merge_knowledge_graphs(explorer_reports)
            merged_principles = _merge_principles(explorer_reports)
            kg_json = merged_kg.model_dump(mode="json")
            principles_json = merged_principles.model_dump(mode="json")

        values_json = extract_values_json(reports_for_extraction)
        roles_json, skills_json, traits_json = await asyncio.gather(
            extract_roles_llm(reports_for_extraction),
            extract_skills_llm(reports_for_extraction),
            extract_traits_llm(reports_for_extraction),
        )

        async with session_factory() as session:
            async with session.begin():
                if mini_id is not None:
                    result = await session.execute(
                        select(Mini).where(Mini.id == mini_id)
                    )
                else:
                    result = await session.execute(
                        select(Mini).where(Mini.username == username)
                    )
                mini = result.scalar_one_or_none()

                if mini is None:
                    logger.error("Mini not found (id=%s, username=%s) during save", mini_id, username)
                    return

                # Snapshot current state as a revision before overwriting
                if mini.spirit_content or mini.system_prompt:
                    from app.models.revision import MiniRevision

                    from sqlalchemy import func as sa_func

                    rev_count_result = await session.execute(
                        select(sa_func.count())
                        .select_from(MiniRevision)
                        .where(MiniRevision.mini_id == mini.id)
                    )
                    next_rev = rev_count_result.scalar_one() + 1
                    trigger = "initial" if next_rev == 1 else "manual_retrain"

                    session.add(MiniRevision(
                        mini_id=mini.id,
                        revision_number=next_rev,
                        spirit_content=mini.spirit_content,
                        memory_content=mini.memory_content,
                        system_prompt=mini.system_prompt,
                        values_json=json.dumps(mini.values_json) if isinstance(mini.values_json, (dict, list)) else mini.values_json,
                        trigger=trigger,
                    ))

                mini.display_name = display_name
                mini.avatar_url = avatar_url
                mini.bio = bio
                mini.spirit_content = spirit_content
                mini.memory_content = memory_content
                mini.system_prompt = system_prompt
                mini.values_json = json.loads(values_json) if isinstance(values_json, str) else values_json
                mini.roles_json = json.loads(roles_json) if isinstance(roles_json, str) else roles_json
                mini.skills_json = json.loads(skills_json) if isinstance(skills_json, str) else skills_json
                mini.traits_json = json.loads(traits_json) if isinstance(traits_json, str) else traits_json
                mini.knowledge_graph_json = kg_json
                mini.principles_json = principles_json
                mini.metadata_json = all_stats
                mini.sources_used = [r.source_name for r in results]
                mini.evidence_cache = evidence_cache
                mini.status = "ready"

        if trace:
            save_span.end()

        await emit(PipelineEvent(
            stage="save", status="completed",
            message="Mini is ready!",
            progress=1.0,
        ))

        # ── EMBED (optional, non-blocking) ───────────────────────────────
        await _generate_embeddings(
            mini_id=mini.id,
            memory_content=memory_content,
            evidence_cache=evidence_cache,
            knowledge_graph_json=kg_json,
            session_factory=session_factory,
        )

    except Exception as e:
        logger.exception("Pipeline failed for %s: %s", username, e)
        await emit(PipelineEvent(
            stage="error", status="failed",
            message=f"Pipeline failed: {str(e)}", progress=0.0,
        ))

        # Update status to failed in DB
        try:
            async with session_factory() as session:
                async with session.begin():
                    if mini_id is not None:
                        result = await session.execute(
                            select(Mini).where(Mini.id == mini_id)
                        )
                    else:
                        result = await session.execute(
                            select(Mini).where(Mini.username == username)
                        )
                    mini = result.scalar_one_or_none()
                    if mini:
                        mini.status = "failed"
        except Exception:
            logger.exception("Failed to update mini status to failed for %s", username)

    finally:
        if langfuse_client:
            langfuse_client.flush()


# In-memory store for pipeline events (keyed by mini_id)
# Used by SSE endpoints to stream progress to clients
_pipeline_events: dict[str, asyncio.Queue[PipelineEvent | None]] = {}


def get_event_queue(mini_id: str) -> asyncio.Queue[PipelineEvent | None]:
    """Get or create an event queue for a mini's pipeline."""
    if mini_id not in _pipeline_events:
        _pipeline_events[mini_id] = asyncio.Queue()
    return _pipeline_events[mini_id]


def cleanup_event_queue(mini_id: str) -> None:
    """Remove the event queue for a mini."""
    _pipeline_events.pop(mini_id, None)


async def run_pipeline_with_events(
    username: str,
    session_factory: Any,
    sources: list[str] | None = None,
    owner_id: str | None = None,
    mini_id: str | None = None,
    source_identifiers: dict[str, str] | None = None,
) -> None:
    """Run pipeline and push events to the in-memory queue for SSE streaming."""
    if mini_id is None:
        raise ValueError("mini_id is required for run_pipeline_with_events")
    queue = get_event_queue(mini_id)

    async def push_event(event: PipelineEvent) -> None:
        await queue.put(event)

    await run_pipeline(
        username, session_factory, on_progress=push_event, sources=sources,
        owner_id=owner_id, mini_id=mini_id,
        source_identifiers=source_identifiers,
    )

    # Signal completion
    await queue.put(None)
