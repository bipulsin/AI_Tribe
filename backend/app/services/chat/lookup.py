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


def _load_claim(db: Session, claim_id: int) -> Claim | None:
    """Load a claim for enterprise chat display (any authenticated user)."""
    return db.scalar(
        select(Claim)
        .options(
            selectinload(Claim.garage),
            selectinload(Claim.vehicles),
            selectinload(Claim.estimate),
            selectinload(Claim.damage_detections),
            selectinload(Claim.images),
        )
        .where(Claim.id == claim_id)
    )


def _format_estimate_lines(line_items: list[dict], *, limit: int = 8) -> list[str]:
    rows: list[str] = []
    for item in line_items[:limit]:
        part = str(item.get("part_name") or "Part").strip()
        damage = str(item.get("damage_type") or "").strip()
        action = str(item.get("repair_or_replace") or "").strip()
        total = float(item.get("line_total") or 0)
        bits = [part]
        if damage:
            bits.append(damage)
        if action:
            bits.append(action)
        label = " · ".join(bits)
        if total > 0:
            rows.append(f"- {label}: ₹{total:,.0f}")
        else:
            rows.append(f"- {label}")
    if len(line_items) > limit:
        rows.append(f"- … and {len(line_items) - limit} more line item(s)")
    return rows


def _build_summary_text(claim: Claim, estimate, line_items: list[dict], detections: list) -> str:
    confidences = [float(d.confidence_score) for d in detections]
    max_confidence = max(confidences) if confidences else None
    vehicle = claim.vehicles[0] if claim.vehicles else None

    status_val = claim.status.value if hasattr(claim.status, "value") else str(claim.status)
    status_label = _STATUS_LABELS.get(claim.status, status_val.replace("_", " ").title())

    lines: list[str] = [
        f"**[{claim.claim_reference}](claim:{claim.id})** — {status_label}",
    ]

    garage_name = claim.garage.name if claim.garage else None
    if garage_name:
        lines.append(f"Garage: {garage_name}")
    if claim.surveyor_name:
        lines.append(f"Surveyor: {claim.surveyor_name}")
    if claim.claimant_name:
        lines.append(f"Claimant: {claim.claimant_name}")
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
        grand = float(estimate.grand_total or 0)
        if grand > 0:
            lines.append(f"Estimate total: ₹{grand:,.0f}")
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

    if line_items:
        lines.append("")
        lines.append("**Estimate line items**")
        lines.extend(_format_estimate_lines(line_items))

    return "\n".join(lines)


def build_claim_detail(db: Session, claim_id: int) -> tuple[str, list[dict]] | None:
    """Build chat text plus widgets (estimate table, photo gallery) for a claim."""
    claim = _load_claim(db, claim_id)
    if not claim:
        return None

    estimate = claim.estimate
    if not estimate:
        estimate = persist_estimate(db, claim.id)
        db.refresh(claim)

    line_items = estimate.line_items or []
    detections = sorted(claim.damage_detections, key=lambda d: d.id)
    text = _build_summary_text(claim, estimate, line_items, detections)

    widgets: list[dict] = []

    images = sorted(
        [img for img in claim.images if not img.is_video],
        key=lambda row: row.image_order,
    )
    if images:
        widgets.append(
            {
                "type": "claim_images",
                "claim_id": claim.id,
                "claim_reference": claim.claim_reference,
                "images": [
                    {
                        "url": f"/uploads/{img.file_path}",
                        "alt": f"{claim.claim_reference} photo {idx + 1}",
                    }
                    for idx, img in enumerate(images[:8])
                ],
            }
        )

    if line_items:
        widgets.append(
            {
                "type": "claim_estimate",
                "claim_id": claim.id,
                "claim_reference": claim.claim_reference,
                "line_items": [
                    {
                        "part_name": item.get("part_name"),
                        "damage_type": item.get("damage_type"),
                        "repair_or_replace": item.get("repair_or_replace"),
                        "unit_price": item.get("unit_price"),
                        "labor_cost": item.get("labor_cost"),
                        "line_total": item.get("line_total"),
                        "price_source": item.get("price_source"),
                    }
                    for item in line_items[:15]
                ],
                "grand_total": float(estimate.grand_total or 0),
                "pricing_complete": _pricing_complete(line_items),
            }
        )

    return text, widgets


def format_claim_summary(db: Session, claim_id: int, user_id: int | None = None) -> str | None:
    """Backward-compatible text-only summary (user_id ignored — enterprise scope)."""
    detail = build_claim_detail(db, claim_id)
    if not detail:
        return None
    text, _widgets = detail
    return text


def format_search_hit_list(hits) -> str:
    lines = ["I found these matching claims — which one did you mean?", ""]
    for idx, hit in enumerate(hits[:8], start=1):
        bits = [
            f"{idx}. **[{hit.claim_reference}](claim:{hit.claim_id})** ({hit.status_label})"
        ]
        if hit.vehicle_label:
            bits.append(hit.vehicle_label)
        if hit.garage_name:
            bits.append(f"@{hit.garage_name}")
        if hit.surveyor_name:
            bits.append(f"surveyor: {hit.surveyor_name}")
        if getattr(hit, "match_hint", None):
            bits.append(f"matched: {hit.match_hint}")
        lines.append(" · ".join(bits))
    lines.append("")
    lines.append("Reply with the claim reference (e.g. CLM-2026-000017) or the list number.")
    return "\n".join(lines)


def format_no_match(query: str) -> str:
    return (
        f"I couldn't find a claim matching “{query}” across references, surveyors, "
        "garages, vehicles, or estimates. Try another name, word, or claim number."
    )


def format_suffix_miss(suffix: str) -> str:
    return (
        f"I couldn't find a claim ending with **{suffix}**. "
        "Try the full reference (e.g. CLM-2026-000026), a garage name, or a city like Pune."
    )
