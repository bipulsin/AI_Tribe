"""Match damage detections to the parts pricing catalogue."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DamageDetection, PartsCatalog, Vehicle
from app.services.parts.damage_aggregation import aggregate_detections

PRICING_CONFIRMED = "confirmed"
PRICING_NEEDS_CONFIRMATION = "needs_confirmation"
PRICING_PROVISIONAL = "provisional_fallback"
PRICING_MODEL_FALLBACK = "model_fallback_priced"
PRICING_PENDING_MANUAL = "pending_manual_prices"
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
    used_model_fallback: bool = False


@dataclass
class MatchContext:
    matches: list[PartMatch]
    pricing_basis: str
    identity_pricing_basis: str
    catalogue_vehicle_label: str
    identified_vehicle_label: str
    fallback_source_model: str | None


@dataclass
class _CatalogHit:
    row: PartsCatalog | None
    exact_model_match: bool
    priced_model: str | None


def _vehicle_for_claim(db: Session, claim_id: int) -> Vehicle | None:
    return db.scalar(select(Vehicle).where(Vehicle.source_claim_id == claim_id))


def _models_equal(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    return a.strip().lower() == b.strip().lower()


def _find_catalog_row(
    db: Session,
    *,
    part_name: str,
    make: str | None,
    model: str | None,
    allow_same_make_fallback: bool,
) -> _CatalogHit:
    """Resolve a catalogue row.

    Exact make+model first. If missing and allow_same_make_fallback, try any
    row for the same make (never cross-brand). No part-name-only fallback.
    """
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
            return _CatalogHit(row, exact_model_match=True, priced_model=row.model)

        if allow_same_make_fallback:
            row = db.scalar(
                select(PartsCatalog).where(
                    part_filter,
                    PartsCatalog.make.ilike(make),
                )
            )
            if row and not _models_equal(row.model, model):
                return _CatalogHit(
                    row, exact_model_match=False, priced_model=row.model
                )
            if row and _models_equal(row.model, model):
                return _CatalogHit(row, exact_model_match=True, priced_model=row.model)
        return _CatalogHit(None, exact_model_match=False, priced_model=None)

    # Make known but no specific model (provisional paths): same-make only.
    if make:
        row = db.scalar(
            select(PartsCatalog).where(
                part_filter,
                PartsCatalog.make.ilike(make),
            )
        )
        if row:
            return _CatalogHit(row, exact_model_match=True, priced_model=row.model)

    return _CatalogHit(None, exact_model_match=False, priced_model=None)


def _pricing_identity(
    vehicle: Vehicle | None,
) -> tuple[str, str | None, str, str, bool]:
    """Return make, model, identity_pricing_basis, identified_label, has_specific_model."""
    if vehicle is not None and vehicle.identity_confirmed:
        make = vehicle.make or DEFAULT_FALLBACK_MAKE
        model = vehicle.model or DEFAULT_FALLBACK_MODEL
        label = f"{make} {model}".strip()
        return make, model, PRICING_CONFIRMED, label, True

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
        return make, model, PRICING_NEEDS_CONFIRMATION, label, bool(model)

    # Nearest-match / ImageNet / stub — identity uncertain.
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
    has_specific = bool(model)
    return (
        make,
        model,
        PRICING_PROVISIONAL,
        label or f"{DEFAULT_FALLBACK_MAKE} {DEFAULT_FALLBACK_MODEL}",
        has_specific,
    )


def match_detections(db: Session, claim_id: int) -> MatchContext:
    detections = db.scalars(
        select(DamageDetection)
        .where(DamageDetection.claim_id == claim_id)
        .order_by(DamageDetection.id.asc())
    ).all()
    detections = aggregate_detections(list(detections))
    vehicle = _vehicle_for_claim(db, claim_id)
    make, model, identity_basis, identified_label, has_specific_model = (
        _pricing_identity(vehicle)
    )

    # Same-make model fallback only when we have a specific identified model.
    allow_same_make_fallback = has_specific_model and identity_basis in {
        PRICING_CONFIRMED,
        PRICING_NEEDS_CONFIRMATION,
    }

    matches: list[PartMatch] = []
    fallback_source_model: str | None = None
    priced_label = identified_label
    any_model_fallback = False

    for detection in detections:
        hit = _find_catalog_row(
            db,
            part_name=detection.part_name,
            make=make,
            model=model,
            allow_same_make_fallback=allow_same_make_fallback,
        )
        if hit.row:
            used_fallback = (
                allow_same_make_fallback
                and not hit.exact_model_match
                and hit.priced_model is not None
            )
            if used_fallback:
                any_model_fallback = True
                fallback_source_model = hit.priced_model
            priced_label = f"{hit.row.make} {hit.row.model}".strip()
            matches.append(
                PartMatch(
                    detection=detection,
                    catalog_row=hit.row,
                    unit_price=float(hit.row.price),
                    labor_hours=float(hit.row.labor_hours),
                    currency=hit.row.currency,
                    matched=True,
                    match_note=(
                        f"{hit.row.make} {hit.row.model} · "
                        f"{hit.row.part_number or hit.row.part_name}"
                        + (
                            f" (same-make fallback from {model})"
                            if used_fallback
                            else ""
                        )
                    ),
                    used_model_fallback=used_fallback,
                )
            )
        else:
            matches.append(
                PartMatch(
                    detection=detection,
                    catalog_row=None,
                    unit_price=0.0,
                    labor_hours=0.0,
                    currency="INR",
                    matched=False,
                    match_note="Price not available — enter manually",
                    used_model_fallback=False,
                )
            )

    if identity_basis == PRICING_PROVISIONAL and matches:
        for match in matches:
            if match.catalog_row:
                priced_label = (
                    f"{match.catalog_row.make} {match.catalog_row.model}".strip()
                )
                break

    if any_model_fallback and fallback_source_model:
        # Catalog used a different same-make model — disclose loudly.
        pricing_basis = PRICING_MODEL_FALLBACK
        catalogue_label = f"{make} {fallback_source_model}".strip()
    elif identity_basis == PRICING_PROVISIONAL:
        pricing_basis = PRICING_PROVISIONAL
        catalogue_label = priced_label
    else:
        pricing_basis = identity_basis
        catalogue_label = identified_label

    return MatchContext(
        matches=matches,
        pricing_basis=pricing_basis,
        identity_pricing_basis=identity_basis,
        catalogue_vehicle_label=catalogue_label,
        identified_vehicle_label=identified_label,
        fallback_source_model=fallback_source_model if any_model_fallback else None,
    )


def match_summary(db: Session, claim_id: int) -> tuple[int, int, str]:
    catalog_count = db.scalar(select(func.count()).select_from(PartsCatalog)) or 0
    context = match_detections(db, claim_id)
    matches = context.matches
    if catalog_count == 0:
        return 0, len(matches), "Pricing catalogue is empty."

    matched = sum(1 for item in matches if item.matched)
    detail = f"Matched {matched} of {len(matches)} parts to the pricing catalogue."
    if context.identity_pricing_basis == PRICING_NEEDS_CONFIRMATION:
        detail += (
            f" Model guess {context.identified_vehicle_label} needs surveyor confirmation."
        )
    if context.fallback_source_model:
        detail += (
            f" Priced via same-make fallback "
            f"({context.identified_vehicle_label} → "
            f"{context.catalogue_vehicle_label})."
        )
    elif context.pricing_basis == PRICING_PROVISIONAL:
        detail += f" Provisional pricing against {context.catalogue_vehicle_label}."
    return matched, len(matches), detail
