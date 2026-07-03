"""Build a survey estimate sheet from matched parts and damage detections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Estimate, Vehicle
from app.models.enums import Severity
from app.services.parts.parts_matcher import PartMatch, match_detections

LABOR_RATE_INR = 450.0
GST_RATE = 0.18

# Repair uses part of the unit price; replace uses full unit price.
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
    subtotal: float,
    tax: float,
    grand_total: float,
    currency: str,
) -> str:
    vehicle_label = "the assessed vehicle"
    if vehicle and vehicle.make:
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
    return (
        f"Total of {currency} {grand_total:,.2f} covers {parts}. "
        f"Parts and materials come to {currency} {materials:,.2f}, "
        f"labour at ₹{LABOR_RATE_INR:.0f}/hr adds {currency} {labor:,.2f}, "
        f"and GST ({GST_RATE:.0%}) is {currency} {tax:,.2f}."
    )


def build_estimate(db: Session, claim_id: int) -> BuiltEstimate:
    matches = match_detections(db, claim_id)
    vehicle = db.scalar(select(Vehicle).where(Vehicle.source_claim_id == claim_id))

    line_items: list[dict[str, Any]] = []
    for match in matches:
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
        subtotal=subtotal,
        tax=tax,
        grand_total=grand_total,
        currency=currency,
    )

    return BuiltEstimate(
        line_items=line_items,
        subtotal=subtotal,
        tax=tax,
        grand_total=grand_total,
        reason_summary=reason,
        currency=currency,
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
            generated_at=datetime.now(timezone.utc),
        )
        db.add(estimate)

    db.commit()
    db.refresh(estimate)
    return estimate
