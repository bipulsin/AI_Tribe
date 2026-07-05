"""Build a survey estimate sheet from matched parts and damage detections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DamageDetection, Estimate, PipelineEvent, Vehicle
from app.models.enums import Severity
from app.services.parts.damage_aggregation import (
    PRICING_EXTENSIVE_DAMAGE,
    assess_extensive_damage,
)
from app.services.parts.parts_matcher import (
    PRICING_MODEL_FALLBACK,
    PRICING_NEEDS_CONFIRMATION,
    PRICING_PROVISIONAL,
    PartMatch,
    match_detections,
)

LABOR_RATE_INR = 450.0
GST_RATE = 0.18

PRICE_DISCLAIMER = (
    "Part prices shown are indicative estimates from publicly available "
    "sources and have not been independently verified. Do not use for binding "
    "settlement decisions."
)

REPAIR_PART_FRACTION = {
    Severity.minor.value: 0.35,
    Severity.moderate.value: 0.55,
    Severity.severe.value: 0.75,
}


@dataclass
class BuiltEstimate:
    line_items: list[dict[str, Any]]
    subtotal: float
    tax: float
    grand_total: float
    reason_summary: str
    currency: str
    pricing_basis: str
    catalogue_vehicle_label: str
    identified_vehicle_label: str
    fallback_source_model: str | None
    identity_pricing_basis: str


def _line_costs(match: PartMatch) -> tuple[float, float, float]:
    detection = match.detection
    severity = (
        detection.severity.value
        if hasattr(detection.severity, "value")
        else str(detection.severity)
    )
    action = (detection.repair_or_replace or "repair").lower()

    if action == "replace":
        unit_price = match.unit_price
        labor_hours = match.labor_hours
    else:
        fraction = REPAIR_PART_FRACTION.get(severity, 0.55)
        unit_price = round(match.unit_price * fraction, 2)
        labor_hours = max(0.5, match.labor_hours * 0.75)

    labor_cost = round(labor_hours * LABOR_RATE_INR, 2)
    total = round(unit_price + labor_cost, 2)
    return unit_price, labor_cost, total


def _reason_summary(
    *,
    vehicle: Vehicle | None,
    line_items: list[dict[str, Any]],
    tax: float,
    grand_total: float,
    currency: str,
    pricing_basis: str,
    identity_pricing_basis: str,
    identified_vehicle_label: str,
    catalogue_vehicle_label: str,
    fallback_source_model: str | None,
    vmmr_inconsistency: str | None = None,
) -> str:
    leads: list[str] = []

    if vmmr_inconsistency:
        leads.append(f"{vmmr_inconsistency} ")

    # Model-fallback disclosure first when present (same placement as provisional).
    if fallback_source_model or pricing_basis == PRICING_MODEL_FALLBACK:
        identified = identified_vehicle_label
        substitute = catalogue_vehicle_label
        if fallback_source_model and vehicle and vehicle.make:
            substitute = f"{vehicle.make} {fallback_source_model}".strip()
        identified_model = (
            (vehicle.model if vehicle and vehicle.model else None)
            or identified.split()[-1]
        )
        leads.append(
            f"Identified vehicle: {identified}. A priced parts catalogue entry "
            f"for this exact model is not yet available, this estimate uses "
            f"{substitute} pricing as an interim approximation and will be "
            f"corrected once {identified_model} catalogue data is added. "
        )

    if identity_pricing_basis == PRICING_NEEDS_CONFIRMATION:
        leads.append(
            f"The model suggested {identified_vehicle_label}, but that class is "
            "in the low-confidence tier and must be confirmed by a surveyor "
            "before this estimate is treated as final. "
        )
    elif identity_pricing_basis == PRICING_PROVISIONAL and not leads:
        leads.append(
            "Vehicle identity could not be confirmed from the submitted photos, "
            f"this estimate is priced against the nearest matched catalogue entry "
            f"({catalogue_vehicle_label}) and should be treated as indicative "
            "until a surveyor confirms the vehicle. "
        )

    lead = "".join(leads)

    if identity_pricing_basis == PRICING_PROVISIONAL and not fallback_source_model:
        vehicle_label = catalogue_vehicle_label
    else:
        vehicle_label = identified_vehicle_label or "the assessed vehicle"
        if vehicle_label == "the assessed vehicle" and vehicle and vehicle.make:
            bits = [vehicle.make]
            if vehicle.model:
                bits.append(vehicle.model)
            if vehicle.year:
                bits.append(str(vehicle.year))
            vehicle_label = " ".join(bits)

    n = len(line_items)
    replace_n = sum(1 for item in line_items if item.get("repair_or_replace") == "replace")
    repair_n = n - replace_n
    parts = (
        f"{n} damaged part{'s' if n != 1 else ''} on {vehicle_label}"
        f" ({repair_n} repair, {replace_n} replace)"
    )
    materials = sum(float(item["unit_price"]) for item in line_items)
    labor = sum(float(item["labor_cost"]) for item in line_items)
    body = (
        f"Total of {currency} {grand_total:,.2f} covers {parts}. "
        f"Parts and materials come to {currency} {materials:,.2f}, "
        f"labour at ₹{LABOR_RATE_INR:.0f}/hr adds {currency} {labor:,.2f}, "
        f"and GST ({GST_RATE:.0%}) is {currency} {tax:,.2f}. "
        f"{PRICE_DISCLAIMER}"
    )
    return f"{lead}{body}"


def _extensive_damage_summary(
    *,
    escalate_reason: str,
    identity_pricing_basis: str,
    identified_vehicle_label: str,
    vmmr_inconsistency: str | None = None,
) -> str:
    leads: list[str] = []
    if vmmr_inconsistency:
        leads.append(f"{vmmr_inconsistency} ")
    leads.append(
        f"Extensive damage signal: {escalate_reason} "
        "A specific priced total has not been auto-generated. "
        "Surveyor confirmation is required before any settlement figure is shown. "
    )
    if identity_pricing_basis == PRICING_NEEDS_CONFIRMATION:
        leads.append(
            f"Vehicle identity ({identified_vehicle_label}) also needs surveyor confirmation. "
        )
    leads.append(PRICE_DISCLAIMER)
    return "".join(leads)


def _vehicle_id_inconsistency(db: Session, claim_id: int) -> str | None:
    event = db.scalar(
        select(PipelineEvent)
        .where(
            PipelineEvent.claim_id == claim_id,
            PipelineEvent.stage_key == "vehicle_id",
        )
        .order_by(PipelineEvent.id.desc())
    )
    if not event or not event.detail:
        return None
    if "inconsistent" in event.detail.lower():
        return event.detail
    return None


def build_estimate(db: Session, claim_id: int) -> BuiltEstimate:
    raw_detections = list(
        db.scalars(
            select(DamageDetection)
            .where(DamageDetection.claim_id == claim_id)
            .order_by(DamageDetection.id.asc())
        ).all()
    )
    escalate, escalate_reason = assess_extensive_damage(raw_detections)
    vmmr_inconsistency = _vehicle_id_inconsistency(db, claim_id)

    context = match_detections(db, claim_id)
    vehicle = db.scalar(select(Vehicle).where(Vehicle.source_claim_id == claim_id))

    if escalate:
        reason = _extensive_damage_summary(
            escalate_reason=escalate_reason,
            identity_pricing_basis=context.identity_pricing_basis,
            identified_vehicle_label=context.identified_vehicle_label,
            vmmr_inconsistency=vmmr_inconsistency,
        )
        return BuiltEstimate(
            line_items=[],
            subtotal=0.0,
            tax=0.0,
            grand_total=0.0,
            reason_summary=reason,
            currency="INR",
            pricing_basis=PRICING_EXTENSIVE_DAMAGE,
            catalogue_vehicle_label=context.catalogue_vehicle_label,
            identified_vehicle_label=context.identified_vehicle_label,
            fallback_source_model=context.fallback_source_model,
            identity_pricing_basis=context.identity_pricing_basis,
        )

    line_items: list[dict[str, Any]] = []
    for match in context.matches:
        unit_price, labor_cost, total = _line_costs(match)
        detection = match.detection
        line_items.append(
            {
                "part_name": detection.part_name,
                "damage_type": (
                    detection.damage_type.value
                    if hasattr(detection.damage_type, "value")
                    else str(detection.damage_type)
                ),
                "severity": (
                    detection.severity.value
                    if hasattr(detection.severity, "value")
                    else str(detection.severity)
                ),
                "repair_or_replace": detection.repair_or_replace,
                "unit_price": unit_price,
                "labor_cost": labor_cost,
                "total": total,
                "currency": match.currency,
                "confidence_score": float(detection.confidence_score),
                "catalogue_match": match.matched,
                "match_note": match.match_note,
                "used_model_fallback": match.used_model_fallback,
            }
        )

    materials_and_labor = sum(item["total"] for item in line_items)
    subtotal = round(materials_and_labor, 2)
    tax = round(subtotal * GST_RATE, 2)
    grand_total = round(subtotal + tax, 2)
    currency = line_items[0]["currency"] if line_items else "INR"

    reason = _reason_summary(
        vehicle=vehicle,
        line_items=line_items,
        tax=tax,
        grand_total=grand_total,
        currency=currency,
        pricing_basis=context.pricing_basis,
        identity_pricing_basis=context.identity_pricing_basis,
        identified_vehicle_label=context.identified_vehicle_label,
        catalogue_vehicle_label=context.catalogue_vehicle_label,
        fallback_source_model=context.fallback_source_model,
        vmmr_inconsistency=vmmr_inconsistency,
    )

    return BuiltEstimate(
        line_items=line_items,
        subtotal=subtotal,
        tax=tax,
        grand_total=grand_total,
        reason_summary=reason,
        currency=currency,
        pricing_basis=context.pricing_basis,
        catalogue_vehicle_label=context.catalogue_vehicle_label,
        identified_vehicle_label=context.identified_vehicle_label,
        fallback_source_model=context.fallback_source_model,
        identity_pricing_basis=context.identity_pricing_basis,
    )


def persist_estimate(db: Session, claim_id: int) -> Estimate:
    built = build_estimate(db, claim_id)

    existing = db.scalar(select(Estimate).where(Estimate.claim_id == claim_id))
    if existing:
        existing.line_items = built.line_items
        existing.subtotal = built.subtotal
        existing.tax = built.tax
        existing.grand_total = built.grand_total
        existing.reason_summary = built.reason_summary
        existing.pricing_basis = built.pricing_basis
        existing.fallback_source_model = built.fallback_source_model
        existing.generated_at = datetime.now(timezone.utc)
        estimate = existing
    else:
        estimate = Estimate(
            claim_id=claim_id,
            line_items=built.line_items,
            subtotal=built.subtotal,
            tax=built.tax,
            grand_total=built.grand_total,
            reason_summary=built.reason_summary,
            pricing_basis=built.pricing_basis,
            fallback_source_model=built.fallback_source_model,
            generated_at=datetime.now(timezone.utc),
        )
        db.add(estimate)

    db.commit()
    db.refresh(estimate)
    return estimate
