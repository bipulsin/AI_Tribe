from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import PipelineEventStatus


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    stage_key: Mapped[str] = mapped_column(String(64), nullable=False)
    stage_label: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[PipelineEventStatus] = mapped_column(
        Enum(PipelineEventStatus, name="pipeline_event_status", native_enum=False),
        nullable=False,
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Unpadded handler runtime (seconds); stage-tracker elapsed may be longer due to demo floor.
    work_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    claim = relationship("Claim", back_populates="pipeline_events")
