"""Intelligent claim search across reference, garage, and surveyor."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Claim, Garage
from app.models.enums import ClaimStatus

# Letters, dash, optional alphanumerics — e.g. CLM-2026-000001, CLM-2026, CLM-
_CLAIM_REF_LIKE = re.compile(r"^[A-Za-z]+(?:-[A-Za-z0-9]*)+$")

_STATUS_LABELS = {
    ClaimStatus.submitted: "Submitted",
    ClaimStatus.processing: "Processing",
    ClaimStatus.authenticity_failed: "Authenticity failed",
    ClaimStatus.review_required: "Review required",
    ClaimStatus.estimate_ready: "Estimate ready",
    ClaimStatus.closed: "Closed",
}


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


def is_claim_reference_like(query: str) -> bool:
    return bool(_CLAIM_REF_LIKE.fullmatch(query.strip()))


def claim_detail_href(claim: Claim) -> str:
    if claim.status == ClaimStatus.estimate_ready:
        return f"/claims/{claim.id}/estimate"
    return f"/claims/{claim.id}/processing"


def search_claims(db: Session, query: str, *, limit: int = 20) -> list[ClaimSearchHit]:
    q = (query or "").strip()
    if len(q) < 1:
        return []

    prefer_reference = is_claim_reference_like(q)
    pattern = f"%{q}%"

    stmt = (
        select(Claim)
        .outerjoin(Garage, Claim.garage_id == Garage.id)
        .options(selectinload(Claim.garage), selectinload(Claim.vehicles))
        .where(
            or_(
                Claim.claim_reference.ilike(pattern),
                Claim.surveyor_name.ilike(pattern),
                Garage.name.ilike(pattern),
            )
        )
        .limit(80)
    )
    claims = list(db.scalars(stmt).unique().all())

    scored: list[tuple[float, Claim]] = []
    q_lower = q.lower()
    for claim in claims:
        score = _score_claim(claim, q_lower, prefer_reference=prefer_reference)
        if score > 0:
            scored.append((score, claim))

    scored.sort(key=lambda item: (-item[0], -(item[1].created_at.timestamp() if item[1].created_at else 0)))

    hits: list[ClaimSearchHit] = []
    for score, claim in scored[:limit]:
        vehicle = claim.vehicles[0] if claim.vehicles else None
        vehicle_label = None
        if vehicle and (vehicle.make or vehicle.model):
            parts = [p for p in (vehicle.make, vehicle.model) if p and p != "Unknown"]
            vehicle_label = " ".join(parts) or None

        garage_name = claim.garage.name if claim.garage else None
        status_val = claim.status.value if hasattr(claim.status, "value") else str(claim.status)
        hits.append(
            ClaimSearchHit(
                claim_id=claim.id,
                claim_reference=claim.claim_reference,
                vehicle_label=vehicle_label,
                garage_name=garage_name,
                surveyor_name=claim.surveyor_name,
                status=status_val,
                status_label=_STATUS_LABELS.get(claim.status, status_val.replace("_", " ").title()),
                created_at=claim.created_at,
                href=claim_detail_href(claim),
                score=score,
            )
        )
    return hits


def _score_claim(claim: Claim, q_lower: str, *, prefer_reference: bool) -> float:
    ref = (claim.claim_reference or "").lower()
    surveyor = (claim.surveyor_name or "").lower()
    garage = (claim.garage.name if claim.garage else "") or ""
    garage = garage.lower()

    score = 0.0

    if ref == q_lower:
        score = max(score, 100.0)
    elif ref.startswith(q_lower):
        score = max(score, 90.0)
    elif q_lower in ref:
        score = max(score, 70.0)

    if garage == q_lower:
        score = max(score, 85.0)
    elif garage.startswith(q_lower):
        score = max(score, 75.0)
    elif q_lower in garage:
        score = max(score, 60.0)

    if surveyor == q_lower:
        score = max(score, 85.0)
    elif surveyor.startswith(q_lower):
        score = max(score, 75.0)
    elif q_lower in surveyor:
        score = max(score, 60.0)

    if prefer_reference and (ref.startswith(q_lower) or ref == q_lower):
        score += 20.0
    elif prefer_reference and q_lower in ref:
        score += 10.0
    elif not prefer_reference:
        # Name-oriented queries: slight boost for garage/surveyor hits over weak ref substrings.
        if (q_lower in garage or q_lower in surveyor) and score < 70:
            score += 5.0

    return score
