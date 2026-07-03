from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import FraudSignalType


class FraudSignal(Base):
    __tablename__ = "fraud_signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False, index=True)
    signal_type: Mapped[FraudSignalType] = mapped_column(
        Enum(FraudSignalType, name="fraud_signal_type", native_enum=False),
        nullable=False,
    )
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    claim = relationship("Claim", back_populates="fraud_signals")
