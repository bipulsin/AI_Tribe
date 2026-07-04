from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Estimate(Base):
    __tablename__ = "estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"), nullable=False, unique=True, index=True
    )
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    tax: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    grand_total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    # confirmed | needs_confirmation | provisional_fallback | model_fallback_priced
    pricing_basis: Mapped[str] = mapped_column(
        String(32), nullable=False, default="provisional_fallback"
    )
    # When pricing_basis is model_fallback_priced (or identity also needs
    # confirmation), the catalogue model actually used for unit prices.
    fallback_source_model: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reason_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    claim = relationship("Claim", back_populates="estimate")
