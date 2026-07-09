"""Persisted chat draft state per user."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChatDraftState(Base):
    __tablename__ = "chat_draft_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    flow: Mapped[str] = mapped_column(String(32), nullable=False, default="submit_claim")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    garage_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    accident_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    surveyor_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    uploaded_files: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
