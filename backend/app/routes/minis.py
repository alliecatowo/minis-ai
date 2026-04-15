import asyncio
import datetime
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.access import require_mini_access, require_mini_owner
from app.core.auth import get_current_user, get_optional_user
from app.core.config import settings
from app.core.rate_limit import check_rate_limit
from app.db import async_session, get_session
from app.models.mini import Mini
from app.models.schemas import CreateMiniRequest, MiniDetail, MiniPublic, MiniSummary
from app.models.user import User
from app.plugins.registry import registry
from app.synthesis.pipeline import (
    cleanup_event_queue,
    get_event_queue,
    run_pipeline_with_events,
)

# ── Dataset endpoint in-memory rate limiter ───────────────────────────────────
# Keyed by mini_id → last generation timestamp (UTC)
_dataset_rate_limit: dict[str, datetime.datetime] = {}
_DATASET_RATE_LIMIT_SECONDS = 600  # 10 minutes

router = APIRouter(prefix="/minis", tags=["minis"])


@router.get("/sources")
async def list_sources():
    """List available ingestion sources."""
    source_names = registry.list_sources()
    source_info = {
        "github": {"name": "GitHub", "description": "Commits, PRs, and reviews"},
        "claude_code": {"name": "Claude Code", "description": "Conversation history"},
        "blog": {"name": "Blog / RSS", "description": "Blog posts and articles via RSS feed"},
        "hackernews": {"name": "Hacker News", "description": "Comments, posts, and tech opinions"},
        "stackoverflow": {"name": "Stack Overflow", "description": "Top answers and expertise"},
        "devblog": {"name": "Dev.to", "description": "Dev.to articles, tutorials, and discussions"},
        "website": {"name": "Website", "description": "Personal or project website pages"},
    }
    return [
        {
            "id": s,
            "name": source_info.get(s, {}).get("name", s),
            "description": source_info.get(s, {}).get("description", ""),
            "available": True,
        }
        for s in source_names
    ]


@router.get("/promo")
async def get_promo_mini(
    session: AsyncSession = Depends(get_session),
):
    """Get the promo mini for anonymous chat. Returns 404 if not configured or not found."""
    promo_username = settings.promo_mini_username
    if not promo_username:
        raise HTTPException(status_code=404, detail="No promo mini configured")

    result = await session.execute(
        select(Mini).where(
            Mini.username == promo_username.lower(),
            Mini.visibility == "public",
        ).order_by(Mini.created_at)
    )
    mini = result.scalars().first()
    if not mini:
        raise HTTPException(status_code=404, detail="Promo mini not found")
    return MiniSummary.model_validate(mini)


@router.post("", status_code=202)
async def create_mini(
    body: CreateMiniRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Create a new mini. Kicks off pipeline in background with selected sources."""
    await check_rate_limit(user.id, "mini_create", session)
    username = body.username.strip().lower()
    sources = body.sources
    owner_id = user.id

    # Check if already exists for this owner
    result = await session.execute(
        select(Mini).where(Mini.username == username, Mini.owner_id == owner_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Re-run pipeline (allows regeneration and recovery from stuck state)
        existing.status = "processing"
        await session.commit()
        mini = existing
    else:
        # Create new
        mini = Mini(username=username, status="processing", owner_id=owner_id)
        session.add(mini)
        await session.commit()
        await session.refresh(mini)

    # Save repo exclusions
    if body.excluded_repos:
        from app.models.ingestion_data import MiniRepoConfig

        for repo_name in body.excluded_repos:
            config = MiniRepoConfig(
                mini_id=mini.id,
                repo_full_name=repo_name,
                included=False,
            )
            session.add(config)
        await session.flush()

    # Kick off pipeline in background
    asyncio.create_task(
        run_pipeline_with_events(
            username, async_session, sources=sources,
            owner_id=owner_id, mini_id=mini.id,
            source_identifiers=body.source_identifiers or None,
        )
    )

    return MiniSummary.model_validate(mini)


@router.get("")
async def list_minis(
    mine: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """List minis. Use ?mine=true to list only your own (requires auth)."""
    if mine:
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required to list your minis")
        result = await session.execute(
            select(Mini).where(Mini.owner_id == user.id).order_by(Mini.created_at.desc())
        )
    else:
        result = await session.execute(
            select(Mini).where(Mini.visibility == "public").order_by(Mini.created_at.desc())
        )
    minis = result.scalars().all()
    return [MiniSummary.model_validate(m) for m in minis]


# NOTE: /by-username route MUST be defined before /{id} to avoid path conflicts
@router.get("/by-username/{username}")
async def get_mini_by_username(
    username: str,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Get a mini by username. Returns user's own if logged in, otherwise first public match."""
    username_lower = username.lower()

    # If logged in, check for user's own mini first
    if user is not None:
        result = await session.execute(
            select(Mini).where(Mini.username == username_lower, Mini.owner_id == user.id)
        )
        own_mini = result.scalar_one_or_none()
        if own_mini:
            return MiniDetail.model_validate(own_mini)

    # Fall back to first public match (non-owner: omit sensitive prompt fields)
    result = await session.execute(
        select(Mini).where(
            Mini.username == username_lower, Mini.visibility == "public"
        ).order_by(Mini.created_at)
    )
    mini = result.scalars().first()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    return MiniPublic.model_validate(mini)


@router.get("/{id}")
async def get_mini(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Get full mini details by ID."""
    result = await session.execute(
        select(Mini).where(Mini.id == id)
    )
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    # Visibility check: private minis are owner-only
    if mini.visibility == "private":
        if user is None or user.id != mini.owner_id:
            raise HTTPException(status_code=404, detail="Mini not found")

    # Owner gets full detail (including system prompt); others get public view
    if user is not None and user.id == mini.owner_id:
        return MiniDetail.model_validate(mini)
    return MiniPublic.model_validate(mini)


@router.delete("/{id}", status_code=204)
async def delete_mini(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Delete a mini. Owner only."""
    result = await session.execute(
        select(Mini).where(Mini.id == id)
    )
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    if mini.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not the owner of this mini")
    await session.delete(mini)
    await session.commit()


@router.get("/{id}/status")
async def mini_status_stream(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """SSE stream of pipeline progress events."""
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if mini:
        require_mini_access(mini, user)
    queue = get_event_queue(id)

    async def event_generator():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=300)
                if event is None:
                    # Pipeline completed
                    yield {"event": "done", "data": "Pipeline completed"}
                    break
                yield {
                    "event": "progress",
                    "data": event.model_dump_json(),
                }
        except asyncio.TimeoutError:
            yield {"event": "timeout", "data": "Pipeline timed out"}
        finally:
            cleanup_event_queue(id)

    return EventSourceResponse(event_generator())


@router.get("/{id}/repos")
async def list_mini_repos(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List repos with their inclusion status for a mini. Owner only."""
    import json

    from app.models.ingestion_data import IngestionData, MiniRepoConfig

    # Get the mini
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    require_mini_owner(mini, user)

    # Get cached repo data
    result = await session.execute(
        select(IngestionData).where(
            IngestionData.mini_id == id,
            IngestionData.source_name == "github",
            IngestionData.data_key == "repos",
        )
    )
    cached = result.scalar_one_or_none()

    repos = []
    if cached:
        try:
            repos = json.loads(cached.data_json)
        except json.JSONDecodeError:
            # Invalid JSON in cache, use empty list
            pass

    # Get repo configs
    result = await session.execute(
        select(MiniRepoConfig).where(MiniRepoConfig.mini_id == id)
    )
    configs = {c.repo_full_name: c.included for c in result.scalars().all()}

    return [
        {
            "name": r.get("name", ""),
            "full_name": r.get("full_name", ""),
            "language": r.get("language"),
            "stars": r.get("stargazers_count", 0),
            "description": r.get("description"),
            "included": configs.get(r.get("full_name", ""), True),
        }
        for r in repos
    ]


@router.get("/{id}/dataset")
async def get_mini_dataset(
    id: str,
    format: str = Query(default="jsonl", pattern="^jsonl$"),
    num_pairs: int = Query(default=20, ge=5, le=100),
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Generate and download a DPO-style fine-tuning dataset for a mini.

    Requires the mini to exist with a soul document (spirit_content). Returns
    JSONL with instruction/chosen/rejected pairs formatted for QLoRA training.
    Rate-limited to one generation per mini per 10 minutes (in-memory).
    """
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    if mini.visibility == "private":
        if user is None or user.id != mini.owner_id:
            raise HTTPException(status_code=404, detail="Mini not found")

    if not mini.spirit_content:
        raise HTTPException(
            status_code=422,
            detail="Mini has no soul document — run the pipeline first before generating a dataset",
        )

    # In-memory rate limiting: one generation per mini per 10 minutes
    now = datetime.datetime.now(datetime.timezone.utc)
    last_gen = _dataset_rate_limit.get(id)
    if last_gen is not None:
        elapsed = (now - last_gen).total_seconds()
        if elapsed < _DATASET_RATE_LIMIT_SECONDS:
            retry_after = int(_DATASET_RATE_LIMIT_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Dataset generation rate-limited. Retry after {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

    _dataset_rate_limit[id] = now

    from app.synthesis.dataset_generator import generate_dataset

    pairs = await generate_dataset(
        spirit_content=mini.spirit_content,
        memory_content=mini.memory_content or "",
        username=mini.username,
        num_pairs=num_pairs,
    )

    # Serialize as JSONL
    lines = [
        json.dumps(
            {
                "instruction": p.instruction,
                "chosen": p.chosen,
                "rejected": p.rejected,
                "skill_type": p.skill_type,
                "source": p.source,
                "example_id": p.example_id,
                "mini_id": id,
                "username": mini.username,
            },
            ensure_ascii=False,
        )
        for p in pairs
    ]
    jsonl_body = "\n".join(lines) + "\n"

    filename = f"{mini.username}_dpo_dataset.jsonl"
    return Response(
        content=jsonl_body,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Pair-Count": str(len(pairs)),
        },
    )


@router.get("/{id}/revisions")
async def list_mini_revisions(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List revision history for a mini. Owner only."""
    from app.models.revision import MiniRevision

    # Check ownership
    mini_result = await session.execute(select(Mini).where(Mini.id == id))
    mini = mini_result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    require_mini_owner(mini, user)

    result = await session.execute(
        select(MiniRevision)
        .where(MiniRevision.mini_id == id)
        .order_by(MiniRevision.revision_number.desc())
    )
    revisions = result.scalars().all()
    return [
        {
            "id": r.id,
            "revision_number": r.revision_number,
            "trigger": r.trigger,
            "created_at": r.created_at,
        }
        for r in revisions
    ]


@router.get("/{id}/graph")
async def get_mini_graph(
    id: str,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    """Return the persisted KnowledgeGraph + PrinciplesMatrix for a mini.

    Implements ADR-001: structured skill/project/concept nodes and edges extracted
    during pipeline exploration. Public for public minis; private minis require auth.
    """
    result = await session.execute(select(Mini).where(Mini.id == id))
    mini = result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")

    if mini.visibility == "private":
        if user is None or user.id != mini.owner_id:
            raise HTTPException(status_code=404, detail="Mini not found")

    if mini.knowledge_graph_json is None and mini.principles_json is None:
        raise HTTPException(
            status_code=404,
            detail="Knowledge graph not yet available — run the pipeline first",
        )

    return {
        "mini_id": mini.id,
        "username": mini.username,
        "knowledge_graph": mini.knowledge_graph_json or {"nodes": [], "edges": []},
        "principles": mini.principles_json or {"principles": []},
    }


@router.get("/{id}/revisions/{revision_id}")
async def get_mini_revision(
    id: str,
    revision_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Get full content of a specific revision. Owner only."""
    from app.models.revision import MiniRevision

    # Check ownership
    mini_result = await session.execute(select(Mini).where(Mini.id == id))
    mini = mini_result.scalar_one_or_none()
    if not mini:
        raise HTTPException(status_code=404, detail="Mini not found")
    require_mini_owner(mini, user)

    result = await session.execute(
        select(MiniRevision).where(
            MiniRevision.id == revision_id,
            MiniRevision.mini_id == id,
        )
    )
    revision = result.scalar_one_or_none()
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
    return {
        "id": revision.id,
        "mini_id": revision.mini_id,
        "revision_number": revision.revision_number,
        "spirit_content": revision.spirit_content,
        "memory_content": revision.memory_content,
        "system_prompt": revision.system_prompt,
        "values_json": revision.values_json,
        "trigger": revision.trigger,
        "created_at": revision.created_at,
    }
