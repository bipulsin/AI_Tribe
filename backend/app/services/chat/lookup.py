"""Format claim summaries for chat responses."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Claim
from app.models.enums import ClaimStatus
from app.services.parts.estimate_builder import PRICE_SOURCE_UNPRICED, persist_estimate

_STATUS_LABELS = {
    ClaimStatus.submitted: "Submitted",
    ClaimStatus.processing: "Processing",
    ClaimStatus.authenticity_failed: "Authenticity failed",
    ClaimStatus.paused_awaiting_vehicle_confirmation: "Awaiting vehicle confirmation",
    ClaimStatus.estimate_ready: "Estimate ready",
    ClaimStatus.closed: "Closed",
}


def _pricing_complete(line_items: list[dict]) -> bool:
    if not line_items:
        return True
    return all(item.get("price_source") != PRICE_SOURCE_UNPRICED for item in line_items)


def _load_claim(db: Session, claim_id: int, user_id: int) -> Claim | None:
    claim = db.scalar(
        select(Claim)
        .options(
            selectinload(Claim.garage),
            selectinload(Claim.vehicles),
            selectinload(Claim.estimate),
            selectinload(Claim.damage_detections),
        )
        .where(Claim.id == claim_id)
    )
    if not claim or claim.created_by != user_id:
        return None
    return claim


def format_claim_summary(db: Session, claim_id: int, user_id: int) -> str | None:
    claim = _load_claim(db, claim_id, user_id)
    if not claim:
        return None

    estimate = claim.estimate
    if not estimate:
        estimate = persist_estimate(db, claim.id)
        db.refresh(claim)

    vehicle = claim.vehicles[0] if claim.vehicles else None
    line_items = estimate.line_items or []
    detections = sorted(claim.damage_detections, key=lambda d: d.id)
    confidences = [float(d.confidence_score) for d in detections]
    max_confidence = max(confidences) if confidences else None

    status_val = claim.status.value if hasattr(claim.status, "value") else str(claim.status)
    status_label = _STATUS_LABELS.get(claim.status, status_val.replace("_", " ").title())

    lines: list[str] = [
        f"**{claim.claim_reference}** — {status_label}",
    ]

    garage_name = claim.garage.name if claim.garage else None
    if garage_name:
        lines.append(f"Garage: {garage_name}")
    if claim.surveyor_name:
        lines.append(f"Surveyor: {claim.surveyor_name}")
    if claim.accident_date:
        lines.append(f"Accident date: {claim.accident_date.isoformat()}")

    if vehicle and (vehicle.make or vehicle.model):
        vehicle_bits = [p for p in (vehicle.make, vehicle.model) if p and p != "Unknown"]
        vehicle_label = " ".join(vehicle_bits) or "Unknown vehicle"
        if vehicle.year:
            vehicle_label += f" ({vehicle.year})"
        if vehicle.identity_confirmed:
            vehicle_label += " · identity confirmed"
        elif claim.status == ClaimStatus.paused_awaiting_vehicle_confirmation:
            vehicle_label += " · needs confirmation"
        lines.append(f"Vehicle: {vehicle_label}")
    else:
        lines.append("Vehicle: identity unconfirmed")

    if max_confidence is not None:
        lines.append(f"Damage confidence: up to {max_confidence * 100:.0f}%")

    if estimate.pricing_basis == "extensive_damage_manual_review":
        lines.append(
            "Assessment: extensive damage — manual review required (no auto settlement total)."
        )
    elif estimate.pricing_basis == "pending_manual_prices":
        lines.append("Pricing: awaiting manual part prices.")
    elif not _pricing_complete(line_items):
        lines.append("Pricing: some line items still unpriced.")
    else:
        total = sum(float(item.get("line_total") or 0) for item in line_items)
        if total > 0:
            lines.append(f"Estimate total: ₹{total:,.0f}")
        elif line_items:
            lines.append("Estimate: line items available (total pending).")

    if detections:
        parts = sorted({d.part_name for d in detections if d.part_name})[:6]
        if parts:
            suffix = "…" if len(detections) > len(parts) else ""
            lines.append(f"Damaged parts: {', '.join(parts)}{suffix}")

    return "\n".join(lines)


def format_search_hit_list(hits) -> str:
    lines = ["I found several matches — which one did you mean?", ""]
    for idx, hit in enumerate(hits[:8], start=1):
        bits = [f"{idx}. **{hit.claim_reference}** ({hit.status_label})"]
        if hit.vehicle_label:
            bits.append(hit.vehicle_label)
        if hit.garage_name:
            bits.append(f"@{hit.garage_name}")
        lines.append(" · ".join(bits))
    lines.append("")
    lines.append("Reply with the claim reference (e.g. CLM-2026-000017) or the list number.")
    return "\n".join(lines)
