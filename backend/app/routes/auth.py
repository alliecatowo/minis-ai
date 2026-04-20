import logging
import re
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.config import settings
from app.db import get_session
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# GitHub login handle pattern: 1–39 chars, alphanumeric + hyphens (no leading/trailing hyphens)
_GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")


class SyncRequest(BaseModel):
    neon_auth_id: str
    github_username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    email: str | None = None

    @field_validator("github_username")
    @classmethod
    def validate_github_username(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Reject display names: any whitespace is a clear signal (e.g. "Allison Coleman")
        if " " in v or "\t" in v:
            raise ValueError(
                f"github_username '{v}' looks like a display name (contains whitespace). "
                "The BFF must send the GitHub login handle, not the display name."
            )
        # Reject values that don't match the GitHub handle pattern
        if not _GITHUB_LOGIN_RE.match(v):
            raise ValueError(
                f"github_username '{v}' is not a valid GitHub login handle "
                "(must match ^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){{0,38}}$)."
            )
        return v


class SyncResponse(BaseModel):
    user_id: str


class UserResponse(BaseModel):
    id: str
    github_username: str | None
    display_name: str | None
    avatar_url: str | None


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)):
    return {"detail": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        github_username=current_user.github_username,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
    )


@router.post("/sync", response_model=SyncResponse)
async def sync_user(
    body: SyncRequest,
    session: AsyncSession = Depends(get_session),
    x_internal_secret: str | None = Header(default=None, alias="X-Internal-Secret"),
):
    """Upsert user from Neon Auth. Returns backend user ID.

    Called by the BFF during the Auth.js signIn flow. The BFF passes Neon Auth
    profile data and receives a backend user ID to embed in the session JWT.

    Requires X-Internal-Secret header matching INTERNAL_API_SECRET env var.
    """
    if not x_internal_secret or not secrets.compare_digest(
        x_internal_secret, settings.internal_api_secret
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if body.github_username is None:
        logger.warning(
            "auth/sync: github_username is null for neon_auth_id=%s — "
            "BFF may have failed to resolve the GitHub login handle.",
            body.neon_auth_id,
        )

    result = await session.execute(select(User).where(User.id == body.neon_auth_id))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            id=body.neon_auth_id,
            github_username=body.github_username,
            display_name=body.display_name,
            avatar_url=body.avatar_url,
        )
        session.add(user)
    else:
        # Only overwrite github_username if the new value is non-null, so a
        # transient GitHub API failure never erases a previously-correct handle.
        if body.github_username is not None:
            user.github_username = body.github_username
        user.display_name = body.display_name
        user.avatar_url = body.avatar_url

    await session.commit()
    await session.refresh(user)

    return SyncResponse(user_id=str(user.id))
