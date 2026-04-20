"""CRUD routes for chat conversations."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db import get_session
from app.models.conversation import Conversation, Message
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/minis/{mini_id}/conversations", tags=["conversations"])


class UpdateConversationRequest(BaseModel):
    title: str = Field(max_length=255)


class ConversationSummary(BaseModel):
    id: str
    mini_id: str
    title: str | None
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    ordinal: int
    created_at: str

    model_config = {"from_attributes": True}


class ConversationDetail(BaseModel):
    id: str
    mini_id: str
    title: str | None
    created_at: str
    updated_at: str
    messages: list[MessageOut]

    model_config = {"from_attributes": True}


@router.get("")
async def list_conversations(
    mini_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List conversations for a mini belonging to the current user."""
    result = await session.execute(
        select(Conversation)
        .where(
            Conversation.mini_id == mini_id,
            Conversation.user_id == user.id,
        )
        .order_by(Conversation.updated_at.desc())
    )
    conversations = result.scalars().all()
    return [
        {
            "id": c.id,
            "mini_id": c.mini_id,
            "title": c.title,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in conversations
    ]


@router.get("/{conversation_id}")
async def get_conversation(
    mini_id: str,
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Get a conversation with all its messages."""
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.mini_id == mini_id,
            Conversation.user_id == user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg_result = await session.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.ordinal)
    )
    messages = msg_result.scalars().all()

    return {
        "id": conversation.id,
        "mini_id": conversation.mini_id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "ordinal": m.ordinal,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.patch("/{conversation_id}")
async def update_conversation(
    mini_id: str,
    conversation_id: str,
    body: UpdateConversationRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Update conversation title."""
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.mini_id == mini_id,
            Conversation.user_id == user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation.title = body.title
    await session.commit()
    return {
        "id": conversation.id,
        "mini_id": conversation.mini_id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    mini_id: str,
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Delete a conversation and all its messages (CASCADE)."""
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.mini_id == mini_id,
            Conversation.user_id == user.id,
        )
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await session.delete(conversation)
    await session.commit()
