from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ClaimStatus


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    garage_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("garages.id"), nullable=True, index=True
    )
    # Display labels for fraud-graph nodes (optional overrides of creator/surveyor).
    claimant_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    surveyor_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claim_status", native_enum=False),
        nullable=False,
        default=ClaimStatus.submitted,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    creator = relationship("User", back_populates="claims")
    garage = relationship("Garage", back_populates="claims")
    images = relationship("ClaimImage", back_populates="claim", cascade="all, delete-orphan")
    pipeline_events = relationship(
        "PipelineEvent", back_populates="claim", cascade="all, delete-orphan"
    )
    vehicles = relationship("Vehicle", back_populates="claim", cascade="all, delete-orphan")
    damage_detections = relationship(
        "DamageDetection", back_populates="claim", cascade="all, delete-orphan"
    )
    fraud_signals = relationship(
        "FraudSignal", back_populates="claim", cascade="all, delete-orphan"
    )
    estimate = relationship(
        "Estimate", back_populates="claim", uselist=False, cascade="all, delete-orphan"
    )
    vmmr_corrections = relationship(
        "VmmrCorrectionQueue", back_populates="claim", cascade="all, delete-orphan"
    )
