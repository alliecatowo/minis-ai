import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.agent import AgentTool, run_agent_streaming
from app.core.audit import log_security_event
from app.core.graph import explore_knowledge_graph_handler
from app.core.auth import get_optional_user
from app.core.encryption import decrypt_value
from app.core.guardrails import check_message
from app.core.rate_limit import check_rate_limit
from app.db import async_session, get_session
from app.models.conversation import Conversation, Message
from app.models.mini import Mini
from app.models.schemas import ChatRequest
from app.models.user import User
from app.models.user_settings import UserSettings

# ---------------------------------------------------------------------------
# Defensive imports for vector-search dependencies.  If either module is
# absent (built by a parallel agent) the code falls back to keyword search.
# ---------------------------------------------------------------------------
_VECTOR_SEARCH_AVAILABLE = False
try:
    from app.core.embeddings import embed_texts  # type: ignore[import]
    from app.models.embeddings import Embedding  # type: ignore[import]
    _VECTOR_SEARCH_AVAILABLE = True
except ImportError:
    logger_init = logging.getLogger(__name__)
    logger_init.debug("Embeddings module not available; chat will use keyword search")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/minis", tags=["chat"])


def _build_chat_tools(mini: Mini, session: AsyncSession | None = None) -> list[AgentTool]:
    """Build the tools available to a mini during chat."""

    def _keyword_search(content: str, query: str, max_results: int = 10) -> str:
        """Score lines by keyword overlap and return top results with context."""
        lines = content.split("\n")
        keywords = [w.lower() for w in query.split() if len(w) > 1]
        if not keywords:
            keywords = [query.lower()]

        # Score each line by how many query keywords appear in it
        scored: list[tuple[int, int]] = []  # (score, line_index)
        for i, line in enumerate(lines):
            line_lower = line.lower()
            score = sum(1 for kw in keywords if kw in line_lower)
            if score > 0:
                scored.append((score, i))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Collect context windows, deduplicating overlapping ranges
        seen_ranges: set[int] = set()
        results: list[str] = []
        for _score, idx in scored:
            if idx in seen_ranges:
                continue
            start = max(0, idx - 2)
            end = min(len(lines), idx + 3)
            # Mark all lines in this range as seen
            for j in range(start, end):
                seen_ranges.add(j)
            context = "\n".join(lines[start:end])
            results.append(context)
            if len(results) >= max_results:
                break

        return "\n\n---\n\n".join(results) if results else ""

    async def _vector_search(query: str, source_type: str, limit: int = 10) -> str | None:
        """Search embeddings table via cosine distance.

        Returns formatted results string, or None if vector search is
        unavailable or this mini has no embeddings of the requested type.
        """
        if not _VECTOR_SEARCH_AVAILABLE or session is None:
            return None
        try:
            # Embed the query
            vectors = await embed_texts([query])
            if not vectors:
                return None
            query_vector = vectors[0]

            # Query using pgvector <=> cosine distance operator
            # We use text() for the ORDER BY clause since SQLAlchemy doesn't
            # natively know about pgvector operators.
            from sqlalchemy import text as sa_text

            rows = await session.execute(
                select(Embedding.content)
                .where(
                    Embedding.mini_id == mini.id,
                    Embedding.source_type == source_type,
                )
                .order_by(
                    Embedding.embedding.op("<=>")(query_vector)
                )
                .limit(limit)
            )
            chunks = [row[0] for row in rows if row[0]]
            if not chunks:
                return None
            return "\n\n---\n\n".join(chunks)
        except Exception:
            logger.debug(
                "Vector search failed for mini=%s source_type=%s, falling back to keyword",
                mini.id,
                source_type,
                exc_info=True,
            )
            return None

    async def search_memories(query: str) -> str:
        """Search the mini's memory bank for facts about a topic."""
        if not mini.memory_content and not _VECTOR_SEARCH_AVAILABLE:
            return "No memories available."
        # Try vector search first
        vector_result = await _vector_search(query, "memory")
        if vector_result is not None:
            return vector_result
        # Fall back to keyword search
        if not mini.memory_content:
            return "No memories available."
        result = _keyword_search(mini.memory_content, query)
        return result or f"No memories found matching '{query}'."

    async def search_evidence(query: str) -> str:
        """Search raw ingestion evidence for quotes and examples."""
        if not mini.evidence_cache and not _VECTOR_SEARCH_AVAILABLE:
            return "No evidence available."
        # Try vector search first
        vector_result = await _vector_search(query, "evidence")
        if vector_result is not None:
            return vector_result
        # Fall back to keyword search
        if not mini.evidence_cache:
            return "No evidence available."
        result = _keyword_search(mini.evidence_cache, query)
        return result or f"No evidence found matching '{query}'."

    async def search_knowledge_graph(query: str) -> str:
        """Search the structured knowledge graph for entities and relationships."""
        if not mini.knowledge_graph_json:
            return "No knowledge graph available."
        try:
            kg_data = mini.knowledge_graph_json if isinstance(mini.knowledge_graph_json, dict) else json.loads(mini.knowledge_graph_json)
        except (json.JSONDecodeError, TypeError):
            return "Knowledge graph data is corrupted."

        nodes = kg_data.get("nodes", [])
        edges = kg_data.get("edges", [])

        query_lower = query.lower()
        keywords = [w.lower() for w in query.split() if len(w) > 1]
        if not keywords:
            keywords = [query_lower]

        # Find matching nodes by name or type
        matching_nodes: list[dict] = []
        for node in nodes:
            name_lower = node.get("name", "").lower()
            type_lower = node.get("type", "").lower()
            score = sum(1 for kw in keywords if kw in name_lower or kw in type_lower)
            if score > 0:
                matching_nodes.append({**node, "_score": score})

        matching_nodes.sort(key=lambda n: n["_score"], reverse=True)
        matching_nodes = matching_nodes[:15]

        if not matching_nodes:
            return f"No knowledge graph entries found matching '{query}'."

        # Format results
        parts: list[str] = []
        for node in matching_nodes:
            node_id = node["id"]
            line = f"**{node['name']}** ({node.get('type', 'unknown')}, depth: {node.get('depth', 0):.1f})"

            # Find connected edges
            connected: list[str] = []
            for edge in edges:
                if edge["source"] == node_id:
                    target_name = edge["target"]
                    # Try to resolve target name
                    for n in nodes:
                        if n["id"] == edge["target"]:
                            target_name = n["name"]
                            break
                    connected.append(f"  - {edge['relation']} -> {target_name}")
                elif edge["target"] == node_id:
                    source_name = edge["source"]
                    for n in nodes:
                        if n["id"] == edge["source"]:
                            source_name = n["name"]
                            break
                    connected.append(f"  - {source_name} {edge['relation']} -> this")

            parts.append(line)
            if connected:
                parts.extend(connected[:10])

        return "\n".join(parts)

    async def explore_knowledge_graph(query: str, traversal_type: str = "search") -> str:
        """Explore the structured knowledge graph using graph traversal algorithms."""
        return await explore_knowledge_graph_handler(
            knowledge_graph_json=mini.knowledge_graph_json,
            query=query,
            traversal_type=traversal_type,
        )

    async def think(reasoning: str) -> str:
        """Internal reasoning step -- work through a problem before responding."""
        return "OK"

    tools = [
        AgentTool(
            name="search_memories",
            description="Search your memory bank for facts, opinions, projects, or experiences related to a topic. Use this to recall specific details before answering.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query -- a keyword or topic to search for in memories",
                    },
                },
                "required": ["query"],
            },
            handler=search_memories,
        ),
        AgentTool(
            name="search_evidence",
            description="Search raw evidence (code reviews, commits, PRs, comments) for exact quotes and examples. Use this when you need to cite specific things you've said or done.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query -- a keyword or topic to search for in raw evidence",
                    },
                },
                "required": ["query"],
            },
            handler=search_evidence,
        ),
        AgentTool(
            name="search_knowledge_graph",
            description="Search your knowledge graph for technologies, projects, concepts, and their relationships. Use this to recall what you know about specific technologies or how things connect.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query -- a technology, project, or concept name to look up",
                    },
                },
                "required": ["query"],
            },
            handler=search_knowledge_graph,
        ),
        AgentTool(
            name="explore_knowledge_graph",
            description=(
                "Explore your knowledge graph using graph traversal algorithms. "
                "Use traversal_type='search' for keyword search (default), "
                "'cluster' to find expertise clusters, "
                "'neighborhood' to explore concepts connected to a node, "
                "'path' to find how two concepts relate (query: 'source->target')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "For 'search'/'neighborhood': concept name or keyword. "
                            "For 'path': 'source->target' (e.g. 'python->django'). "
                            "For 'cluster': ignored (pass any string)."
                        ),
                    },
                    "traversal_type": {
                        "type": "string",
                        "enum": ["search", "path", "cluster", "neighborhood"],
                        "description": "Type of graph traversal to perform.",
                    },
                },
                "required": ["query"],
            },
            handler=explore_knowledge_graph,
        ),
        AgentTool(
            name="think",
            description="Think through a problem step by step before responding. Use this for complex questions that require reasoning.",
            parameters={
                "type": "object",
                "properties": {
                    "reasoning": {
                        "type": "string",
                        "description": "Your step-by-step reasoning about the question",
                    },
                },
                "required": ["reasoning"],
            },
            handler=think,
        ),
    ]

    return tools


@router.post("/{mini_id}/chat")
async def chat_with_mini(
    mini_id: str,
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Send a message and get a streaming SSE response from the mini using agentic chat."""
    result = await session.execute(
        select(Mini).where(Mini.id == mini_id)
    )
    mini = result.scalar_one_or_none()

    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    # Visibility check: private minis are owner-only
    if mini.visibility == "private":
        if user is None or user.id != mini.owner_id:
            raise HTTPException(status_code=404, detail="Mini not found")

    if mini.status != "ready":
        raise HTTPException(status_code=409, detail=f"Mini is not ready (status: {mini.status})")
    if not mini.system_prompt:
        raise HTTPException(status_code=500, detail="Mini has no system prompt")

    # Rate limit check (only for authenticated users)
    if user is not None:
        await check_rate_limit(user.id, "chat_message", session)

    # Resolve model and API key from user settings
    resolved_model: str | None = None
    resolved_api_key: str | None = None
    if user is not None:
        result = await session.execute(
            select(UserSettings).where(UserSettings.user_id == user.id)
        )
        user_settings = result.scalar_one_or_none()
        if user_settings:
            resolved_model = user_settings.preferred_model
            if user_settings.llm_api_key:
                try:
                    resolved_api_key = decrypt_value(user_settings.llm_api_key)
                except Exception:
                    resolved_api_key = None

    system_prompt = mini.system_prompt

    # ── Guardrail checks (before LLM call) ───────────────────────────────
    history_dicts: list[dict] = [
        {"role": msg.role, "content": msg.content} for msg in body.history
    ]
    guardrail_result = check_message(body.message, history=history_dicts)
    if guardrail_result.injection_matches:
        log_security_event(
            "prompt_injection_attempt",
            user_id=user.id if user else None,
            detail=f"Matched {len(guardrail_result.injection_matches)} pattern(s)",
        )

    # ── Conversation persistence setup ─────────────────────────────────────
    conversation_id = body.conversation_id
    if user is not None and conversation_id:
        # Validate the conversation belongs to this user and mini
        conv_result = await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.mini_id == mini_id,
                Conversation.user_id == user.id,
            )
        )
        if conv_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    elif user is not None and not conversation_id:
        # Create a new conversation
        conversation_id = str(uuid.uuid4())
        new_conv = Conversation(
            id=conversation_id,
            mini_id=mini_id,
            user_id=user.id,
            title=body.message[:100] if body.message else None,
        )
        session.add(new_conv)
        await session.commit()

    # Save the user message
    if user is not None and conversation_id:
        # Get next ordinal
        ord_result = await session.execute(
            select(func.coalesce(func.max(Message.ordinal), -1)).where(
                Message.conversation_id == conversation_id,
            )
        )
        next_ordinal = ord_result.scalar() + 1
        user_msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="user",
            content=body.message,
            ordinal=next_ordinal,
        )
        session.add(user_msg)
        await session.commit()

    tools = _build_chat_tools(mini, session=session)

    # ── Output filtering: detect system prompt leakage ───────────────────
    # Extract distinctive phrases from the system prompt to check against output.
    # We use section headers and unique multi-word phrases.
    _LEAKAGE_MARKERS = [
        "IDENTITY DIRECTIVE",
        "PERSONALITY & STYLE",
        "ANTI-VALUES & DON'Ts",
        "BEHAVIORAL GUIDELINES",
        "SYSTEM PROMPT PROTECTION",
        "You ARE " + (mini.username or ""),
        "Not an AI playing a character",
        "digital twin of",
        "Voice Matching Checklist",
        "Voice Matching Rules",
    ]

    def _check_leakage(text: str) -> bool:
        """Return True if text contains system prompt markers."""
        text_upper = text.upper()
        for marker in _LEAKAGE_MARKERS:
            if marker.upper() in text_upper:
                return True
        return False

    # Capture conversation_id and user for the generator closure
    _conv_id = conversation_id
    _user = user

    async def event_generator():
        accumulated_text = ""

        # Emit conversation_id so the client can track it
        if _conv_id:
            yield {"event": "conversation_id", "data": _conv_id}

        async for event in run_agent_streaming(
            system_prompt=system_prompt,
            user_prompt=body.message,
            tools=tools,
            history=history_dicts,
            max_turns=15,
            model=resolved_model,
            api_key=resolved_api_key,
        ):
            # Check streaming chunks for system prompt leakage
            if event.type == "chunk":
                accumulated_text += event.data
                # Check every ~200 chars to avoid per-char overhead
                if len(accumulated_text) > 200:
                    if _check_leakage(accumulated_text):
                        logger.warning(
                            "System prompt leakage detected in response for mini=%s",
                            mini_id,
                        )
                        log_security_event(
                            "system_prompt_leakage",
                            user_id=_user.id if _user else None,
                            detail=f"mini={mini_id}",
                        )
                        yield {
                            "event": "error",
                            "data": "Response filtered: potential system prompt leakage detected.",
                        }
                        return
            yield {"event": event.type, "data": event.data}

        # Final check on complete accumulated text
        if accumulated_text and _check_leakage(accumulated_text):
            logger.warning(
                "System prompt leakage detected in final response for mini=%s",
                mini_id,
            )
            log_security_event(
                "system_prompt_leakage",
                user_id=_user.id if _user else None,
                detail=f"mini={mini_id} (final check)",
            )

        # Persist assistant message after streaming completes
        if _user is not None and _conv_id and accumulated_text:
            try:
                async with async_session() as save_session:
                    ord_result = await save_session.execute(
                        select(func.coalesce(func.max(Message.ordinal), -1)).where(
                            Message.conversation_id == _conv_id,
                        )
                    )
                    next_ord = ord_result.scalar() + 1
                    assistant_msg = Message(
                        id=str(uuid.uuid4()),
                        conversation_id=_conv_id,
                        role="assistant",
                        content=accumulated_text,
                        ordinal=next_ord,
                    )
                    save_session.add(assistant_msg)
                    await save_session.commit()
            except Exception:
                logger.exception("Failed to persist assistant message for conversation=%s", _conv_id)

    return EventSourceResponse(event_generator())
