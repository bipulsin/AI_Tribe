from sqlalchemy import Enum, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import DamageType, Severity


class DamageDetection(Base):
    __tablename__ = "damage_detections"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    claim_image_id: Mapped[int] = mapped_column(
        ForeignKey("claim_images.id"), nullable=False, index=True
    )
    part_name: Mapped[str] = mapped_column(String(128), nullable=False)
    damage_type: Mapped[DamageType] = mapped_column(
        Enum(DamageType, name="damage_type", native_enum=False),
        nullable=False,
    )
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity", native_enum=False),
        nullable=False,
    )
    repair_or_replace: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    claim = relationship("Claim", back_populates="damage_detections")
    claim_image = relationship("ClaimImage", back_populates="damage_detections")
