from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserLlmPreferences(Base):
    __tablename__ = "user_llm_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    active_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    toggle_deepfake: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    toggle_vmmr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    toggle_estimation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    toggle_fraud: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("User", back_populates="llm_preferences")
