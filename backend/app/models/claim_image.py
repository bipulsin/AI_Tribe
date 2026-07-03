from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AuthenticityVerdict


class ClaimImage(Base):
    __tablename__ = "claim_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    image_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_video: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quality_gate_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    authenticity_verdict: Mapped[AuthenticityVerdict | None] = mapped_column(
        Enum(AuthenticityVerdict, name="authenticity_verdict", native_enum=False),
        nullable=True,
        default=AuthenticityVerdict.pending,
    )
    authenticity_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    phash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    claim = relationship("Claim", back_populates="images")
    damage_detections = relationship("DamageDetection", back_populates="claim_image")
