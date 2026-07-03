"""Match damage detections to the parts pricing catalogue."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DamageDetection, PartsCatalog, Vehicle


@dataclass
class PartMatch:
    detection: DamageDetection
    catalog_row: PartsCatalog | None
    unit_price: float
    labor_hours: float
    currency: str
    matched: bool
    match_note: str


def _vehicle_for_claim(db: Session, claim_id: int) -> Vehicle | None:
    return db.scalar(select(Vehicle).where(Vehicle.source_claim_id == claim_id))


def _find_catalog_row(
    db: Session,
    *,
    part_name: str,
    make: str | None,
    model: str | None,
) -> PartsCatalog | None:
    part_filter = PartsCatalog.part_name.ilike(part_name)

    if make and model:
        row = db.scalar(
            select(PartsCatalog).where(
                part_filter,
                PartsCatalog.make.ilike(make),
                PartsCatalog.model.ilike(model),
            )
        )
        if row:
            return row

    if make:
        row = db.scalar(
            select(PartsCatalog).where(
                part_filter,
                PartsCatalog.make.ilike(make),
            )
        )
        if row:
            return row

    # Fall back to any catalogue row with the same part name (demo-friendly).
    return db.scalar(select(PartsCatalog).where(part_filter))


def match_detections(db: Session, claim_id: int) -> list[PartMatch]:
    detections = db.scalars(
        select(DamageDetection)
        .where(DamageDetection.claim_id == claim_id)
        .order_by(DamageDetection.id.asc())
    ).all()
    vehicle = _vehicle_for_claim(db, claim_id)
    make = vehicle.make if vehicle and vehicle.make and vehicle.make != "Unknown" else None
    model = vehicle.model if vehicle and vehicle.model and vehicle.model != "Unknown" else None

    # Stub VMMR often returns Maruti Swift — prefer that catalogue when identity is unknown.
    if not make:
        make = "Maruti"
        model = "Swift"

    matches: list[PartMatch] = []
    for detection in detections:
        catalog_row = _find_catalog_row(
            db,
            part_name=detection.part_name,
            make=make,
            model=model,
        )
        if catalog_row:
            matches.append(
                PartMatch(
                    detection=detection,
                    catalog_row=catalog_row,
                    unit_price=float(catalog_row.price),
                    labor_hours=float(catalog_row.labor_hours),
                    currency=catalog_row.currency,
                    matched=True,
                    match_note=(
                        f"{catalog_row.make} {catalog_row.model} · "
                        f"{catalog_row.part_number or catalog_row.part_name}"
                    ),
                )
            )
        else:
            # Conservative fallback so the estimate sheet still renders.
            matches.append(
                PartMatch(
                    detection=detection,
                    catalog_row=None,
                    unit_price=5000.0,
                    labor_hours=2.0,
                    currency="INR",
                    matched=False,
                    match_note="Catalogue miss — provisional price applied",
                )
            )
    return matches


def match_summary(db: Session, claim_id: int) -> tuple[int, int, str]:
    catalog_count = db.scalar(select(func.count()).select_from(PartsCatalog)) or 0
    matches = match_detections(db, claim_id)
    if catalog_count == 0:
        return 0, len(matches), "Pricing catalogue is empty."

    matched = sum(1 for item in matches if item.matched)
    detail = f"Matched {matched} of {len(matches)} parts to the pricing catalogue."
    return matched, len(matches), detail
