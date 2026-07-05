from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    make: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    variant: Mapped[str | None] = mapped_column(String(64), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plate_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # True only when VMMR auto-finalizes (reliable tier + margin gate).
    identity_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # confirmed | needs_confirmation | provisional_fallback
    pricing_basis: Mapped[str] = mapped_column(
        String(32), nullable=False, default="provisional_fallback"
    )
    # vmmr | manual_entry — how identity was established.
    identity_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="vmmr"
    )
    source_claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"), nullable=False, index=True
    )

    claim = relationship("Claim", back_populates="vehicles")
