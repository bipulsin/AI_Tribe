"""Match damage detections to the parts pricing catalogue."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DamageDetection, PartsCatalog, Vehicle

PRICING_CONFIRMED = "confirmed"
PRICING_NEEDS_CONFIRMATION = "needs_confirmation"
PRICING_PROVISIONAL = "provisional_fallback"
DEFAULT_FALLBACK_MAKE = "Maruti"
DEFAULT_FALLBACK_MODEL = "Swift"


@dataclass
class PartMatch:
    detection: DamageDetection
    catalog_row: PartsCatalog | None
    unit_price: float
    labor_hours: float
    currency: str
    matched: bool
    match_note: str


@dataclass
class MatchContext:
    matches: list[PartMatch]
    pricing_basis: str
    catalogue_vehicle_label: str


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

    return db.scalar(select(PartsCatalog).where(part_filter))


def _pricing_identity(vehicle: Vehicle | None) -> tuple[str, str | None, str, str]:
    """Return make, model, pricing_basis, catalogue_vehicle_label."""
    if vehicle is not None and vehicle.identity_confirmed:
        make = vehicle.make or DEFAULT_FALLBACK_MAKE
        model = vehicle.model or DEFAULT_FALLBACK_MODEL
        label = f"{make} {model}".strip()
        return make, model, PRICING_CONFIRMED, label

    # Specific fine-tuned guess in a low_confidence tier — price against that
    # catalogue entry but require surveyor confirmation (not auto-final).
    basis = getattr(vehicle, "pricing_basis", None) if vehicle else None
    if (
        vehicle is not None
        and basis == PRICING_NEEDS_CONFIRMATION
        and vehicle.make
        and vehicle.make != "Unknown"
    ):
        make = vehicle.make
        model = (
            vehicle.model
            if vehicle.model and vehicle.model != "Unknown"
            else None
        )
        label = f"{make} {model}".strip() if model else make
        return make, model, PRICING_NEEDS_CONFIRMATION, label

    # Nearest-match / ImageNet / stub fallback — never treat as confirmed identity.
    make = DEFAULT_FALLBACK_MAKE
    model = DEFAULT_FALLBACK_MODEL
    if vehicle and vehicle.make and vehicle.make != "Unknown":
        make = vehicle.make
        model = (
            vehicle.model
            if vehicle.model and vehicle.model != "Unknown"
            else None
        )
    label = f"{make} {model}".strip() if model else make
    return (
        make,
        model,
        PRICING_PROVISIONAL,
        label or f"{DEFAULT_FALLBACK_MAKE} {DEFAULT_FALLBACK_MODEL}",
    )


def match_detections(db: Session, claim_id: int) -> MatchContext:
    detections = db.scalars(
        select(DamageDetection)
        .where(DamageDetection.claim_id == claim_id)
        .order_by(DamageDetection.id.asc())
    ).all()
    vehicle = _vehicle_for_claim(db, claim_id)
    make, model, pricing_basis, catalogue_label = _pricing_identity(vehicle)

    matches: list[PartMatch] = []
    resolved_label = catalogue_label
    for detection in detections:
        catalog_row = _find_catalog_row(
            db,
            part_name=detection.part_name,
            make=make,
            model=model,
        )
        if catalog_row:
            resolved_label = f"{catalog_row.make} {catalog_row.model}".strip()
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

    if pricing_basis in {PRICING_PROVISIONAL, PRICING_NEEDS_CONFIRMATION} and matches:
        # Prefer the concrete catalogue vehicle actually used for pricing copy.
        for match in matches:
            if match.catalog_row:
                resolved_label = (
                    f"{match.catalog_row.make} {match.catalog_row.model}".strip()
                )
                break

    return MatchContext(
        matches=matches,
        pricing_basis=pricing_basis,
        catalogue_vehicle_label=resolved_label,
    )


def match_summary(db: Session, claim_id: int) -> tuple[int, int, str]:
    catalog_count = db.scalar(select(func.count()).select_from(PartsCatalog)) or 0
    context = match_detections(db, claim_id)
    matches = context.matches
    if catalog_count == 0:
        return 0, len(matches), "Pricing catalogue is empty."

    matched = sum(1 for item in matches if item.matched)
    detail = f"Matched {matched} of {len(matches)} parts to the pricing catalogue."
    if context.pricing_basis == PRICING_PROVISIONAL:
        detail += f" Provisional pricing against {context.catalogue_vehicle_label}."
    elif context.pricing_basis == PRICING_NEEDS_CONFIRMATION:
        detail += (
            f" Model guess {context.catalogue_vehicle_label} needs surveyor confirmation."
        )
    return matched, len(matches), detail
