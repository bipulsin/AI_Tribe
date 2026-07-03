from sqlalchemy import ForeignKey, Integer, String
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
    source_claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"), nullable=False, index=True
    )

    claim = relationship("Claim", back_populates="vehicles")
