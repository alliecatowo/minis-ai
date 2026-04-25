import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mini import Base


class UserSettings(Base):
    __tablename__ = "user_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), unique=True)
    llm_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_provider: Mapped[str] = mapped_column(String(50), default="gemini")
    preferred_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_preferences: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Legacy display flag only. Admin authorization must use a trusted
    # server-side source such as ADMIN_USERNAMES, never this mutable row.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
