"""Intelligent claim search across reference, people, garage, vehicle, and estimate."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Claim, Estimate, Garage, Vehicle
from app.models.enums import ClaimStatus

# Letters, dash, optional alphanumerics — e.g. CLM-2026-000001, CLM-2026, CLM-
_CLAIM_REF_LIKE = re.compile(r"^[A-Za-z]+(?:-[A-Za-z0-9]*)+$")

_STATUS_LABELS = {
    ClaimStatus.submitted: "Submitted",
    ClaimStatus.processing: "Processing",
    ClaimStatus.authenticity_failed: "Authenticity failed",
    ClaimStatus.paused_awaiting_vehicle_confirmation: "Awaiting vehicle confirmation",
    ClaimStatus.estimate_ready: "Estimate ready",
    ClaimStatus.closed: "Closed",
}

_ESTIMATE_LINE_KEYS = ("part_name", "damage_type", "repair_or_replace", "notes")


@dataclass(frozen=True)
class ClaimSearchHit:
    claim_id: int
    claim_reference: str
    vehicle_label: str | None
    garage_name: str | None
    surveyor_name: str | None
    status: str
    status_label: str
    created_at: datetime | None
    href: str
    score: float
    match_hint: str | None = None


def is_claim_reference_like(query: str) -> bool:
    return bool(_CLAIM_REF_LIKE.fullmatch(query.strip()))


def claim_detail_href(claim: Claim) -> str:
    if claim.status == ClaimStatus.estimate_ready:
        return f"/claims/{claim.id}/estimate"
    return f"/claims/{claim.id}/processing"


def _vehicle_label(claim: Claim) -> str | None:
    vehicle = claim.vehicles[0] if claim.vehicles else None
    if not vehicle or not (vehicle.make or vehicle.model):
        return None
    parts = [p for p in (vehicle.make, vehicle.model) if p and p != "Unknown"]
    return " ".join(parts) or None


def _claim_to_hit(claim: Claim, score: float, *, match_hint: str | None = None) -> ClaimSearchHit:
    garage_name = claim.garage.name if claim.garage else None
    status_val = claim.status.value if hasattr(claim.status, "value") else str(claim.status)
    return ClaimSearchHit(
        claim_id=claim.id,
        claim_reference=claim.claim_reference,
        vehicle_label=_vehicle_label(claim),
        garage_name=garage_name,
        surveyor_name=claim.surveyor_name,
        status=status_val,
        status_label=_STATUS_LABELS.get(claim.status, status_val.replace("_", " ").title()),
        created_at=claim.created_at,
        href=claim_detail_href(claim),
        score=score,
        match_hint=match_hint,
    )


def _estimate_text_blob(estimate: Estimate | None) -> str:
    if not estimate:
        return ""
    chunks = [estimate.reason_summary or ""]
    for item in estimate.line_items or []:
        for key in _ESTIMATE_LINE_KEYS:
            val = item.get(key)
            if val:
                chunks.append(str(val))
    return " ".join(chunks).lower()


def _match_hint_for_claim(claim: Claim, q_lower: str) -> str | None:
    ref = (claim.claim_reference or "").lower()
    if q_lower in ref:
        return "claim reference"

    surveyor = (claim.surveyor_name or "").lower()
    if q_lower in surveyor:
        return "surveyor"

    claimant = (claim.claimant_name or "").lower()
    if q_lower in claimant:
        return "claimant"

    garage = ((claim.garage.name if claim.garage else "") or "").lower()
    if q_lower in garage:
        return "garage"

    for vehicle in claim.vehicles:
        for label, value in (
            ("vehicle make", vehicle.make),
            ("vehicle model", vehicle.model),
            ("vehicle", vehicle.variant),
        ):
            val = (value or "").lower()
            if q_lower in val:
                return label

    est_text = _estimate_text_blob(claim.estimate)
    if q_lower in est_text:
        return "estimate"
    return None


def search_claims(
    db: Session, query: str, *, limit: int = 20, user_id: int | None = None
) -> list[ClaimSearchHit]:
    q = (query or "").strip()
    if len(q) < 1:
        return []

    prefer_reference = is_claim_reference_like(q)
    pattern = f"%{q}%"
    q_lower = q.lower()

    stmt = (
        select(Claim)
        .outerjoin(Garage, Claim.garage_id == Garage.id)
        .outerjoin(Vehicle, Vehicle.source_claim_id == Claim.id)
        .outerjoin(Estimate, Estimate.claim_id == Claim.id)
        .options(
            selectinload(Claim.garage),
            selectinload(Claim.vehicles),
            selectinload(Claim.estimate),
        )
        .where(
            or_(
                Claim.claim_reference.ilike(pattern),
                Claim.surveyor_name.ilike(pattern),
                Claim.claimant_name.ilike(pattern),
                Garage.name.ilike(pattern),
                Vehicle.make.ilike(pattern),
                Vehicle.model.ilike(pattern),
                Vehicle.variant.ilike(pattern),
                Estimate.reason_summary.ilike(pattern),
                cast(Estimate.line_items, String).ilike(pattern),
            )
        )
        .limit(120)
    )
    if user_id is not None:
        stmt = stmt.where(Claim.created_by == user_id)
    claims = list(db.scalars(stmt).unique().all())

    scored: list[tuple[float, Claim, str | None]] = []
    for claim in claims:
        score = _score_claim(claim, q_lower, prefer_reference=prefer_reference)
        if score > 0:
            hint = _match_hint_for_claim(claim, q_lower)
            scored.append((score, claim, hint))

    scored.sort(
        key=lambda item: (
            -item[0],
            -(item[1].created_at.timestamp() if item[1].created_at else 0),
        )
    )

    hits: list[ClaimSearchHit] = []
    for score, claim, hint in scored[:limit]:
        hits.append(_claim_to_hit(claim, score, match_hint=hint))
    return hits


def search_claims_by_reference_suffix(
    db: Session, suffix: str, *, limit: int = 20, user_id: int | None = None
) -> list[ClaimSearchHit]:
    """Find claims whose reference ends with the padded suffix (e.g. 00026)."""
    sfx = (suffix or "").strip()
    if not sfx:
        return []

    pattern = f"%{sfx}"
    stmt = (
        select(Claim)
        .outerjoin(Garage, Claim.garage_id == Garage.id)
        .options(
            selectinload(Claim.garage),
            selectinload(Claim.vehicles),
            selectinload(Claim.estimate),
        )
        .where(Claim.claim_reference.ilike(pattern))
        .limit(80)
    )
    if user_id is not None:
        stmt = stmt.where(Claim.created_by == user_id)
    claims = list(db.scalars(stmt).unique().all())

    matched = [
        c
        for c in claims
        if (c.claim_reference or "").upper().endswith(sfx.upper())
    ]
    matched.sort(key=lambda c: -(c.created_at.timestamp() if c.created_at else 0))

    return [
        _claim_to_hit(claim, 100.0, match_hint="claim reference")
        for claim in matched[:limit]
    ]


def _score_claim(claim: Claim, q_lower: str, *, prefer_reference: bool) -> float:
    ref = (claim.claim_reference or "").lower()
    surveyor = (claim.surveyor_name or "").lower()
    claimant = (claim.claimant_name or "").lower()
    garage = (claim.garage.name if claim.garage else "") or ""
    garage = garage.lower()

    score = 0.0

    if ref == q_lower:
        score = max(score, 100.0)
    elif ref.startswith(q_lower):
        score = max(score, 90.0)
    elif q_lower in ref:
        score = max(score, 70.0)

    if surveyor == q_lower:
        score = max(score, 88.0)
    elif any(q_lower in part for part in surveyor.split()):
        score = max(score, 82.0)
    elif surveyor.startswith(q_lower):
        score = max(score, 78.0)
    elif q_lower in surveyor:
        score = max(score, 72.0)

    if claimant == q_lower:
        score = max(score, 86.0)
    elif any(q_lower in part for part in claimant.split()):
        score = max(score, 80.0)
    elif claimant.startswith(q_lower):
        score = max(score, 76.0)
    elif q_lower in claimant:
        score = max(score, 70.0)

    if garage == q_lower:
        score = max(score, 85.0)
    elif garage.startswith(q_lower):
        score = max(score, 75.0)
    elif q_lower in garage:
        score = max(score, 60.0)

    for vehicle in claim.vehicles:
        for field in (vehicle.make, vehicle.model, vehicle.variant):
            val = (field or "").lower()
            if not val or val == "unknown":
                continue
            if val == q_lower:
                score = max(score, 84.0)
            elif val.startswith(q_lower):
                score = max(score, 76.0)
            elif q_lower in val:
                score = max(score, 68.0)

    estimate = claim.estimate
    if estimate:
        reason = (estimate.reason_summary or "").lower()
        if q_lower in reason:
            score = max(score, 58.0)
        for item in estimate.line_items or []:
            for key in _ESTIMATE_LINE_KEYS:
                val = str(item.get(key) or "").lower()
                if not val:
                    continue
                if val == q_lower:
                    score = max(score, 74.0)
                elif q_lower in val:
                    score = max(score, 64.0)

    if prefer_reference and (ref.startswith(q_lower) or ref == q_lower):
        score += 20.0
    elif prefer_reference and q_lower in ref:
        score += 10.0
    elif not prefer_reference:
        if (q_lower in garage or q_lower in surveyor or q_lower in claimant) and score < 70:
            score += 5.0

    return score
