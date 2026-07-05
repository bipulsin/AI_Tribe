from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class VmmrCorrectionQueue(Base):
    __tablename__ = "vmmr_correction_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    image_paths: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    scratch_image_paths: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    confirmed_make: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_model: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    used_in_training: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    claim = relationship("Claim", back_populates="vmmr_corrections")
    submitter = relationship("User")
