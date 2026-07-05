"""Human-reviewed make/model labels from offline lab datasets (not live claims)."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

LICENSE_VEHIDE_NC_LAB = "vehide_nc_lab_only"


class VmmrLabLabel(Base):
    __tablename__ = "vmmr_lab_labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_dataset: Mapped[str] = mapped_column(String(32), nullable=False, default="vehide")
    image_path: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    image_rel_path: Mapped[str | None] = mapped_column(String(256), nullable=True)
    damage_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    suggested_make: Mapped[str | None] = mapped_column(String(64), nullable=True)
    suggested_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    suggested_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    guess_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    guess_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_alternatives: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    confirmed_make: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    license_tag: Mapped[str] = mapped_column(
        String(64), nullable=False, default=LICENSE_VEHIDE_NC_LAB
    )
    scratch_copy_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    labeled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    labeled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    labeler = relationship("User")
