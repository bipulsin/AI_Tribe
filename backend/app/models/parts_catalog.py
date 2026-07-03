from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PartsCatalog(Base):
    __tablename__ = "parts_catalog"

    id: Mapped[int] = mapped_column(primary_key=True)
    make: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    part_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    part_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    labor_hours: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=1.0)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    region: Mapped[str] = mapped_column(String(32), nullable=False, default="IN")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="seed_india_v1")
