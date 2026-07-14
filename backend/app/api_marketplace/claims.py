"""External claim operations — thin wrappers over existing claim/pipeline services."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.datastructures import UploadFile

from app.api_marketplace.cache import cache_get, cache_invalidate_prefix, cache_set
from app.api_marketplace.crypto import mint_upload_token, parse_upload_token, TokenCryptoError
from app.models import Claim, DamageDetection, Estimate, Garage, PipelineEvent, Vehicle
from app.models.enums import ClaimStatus
from app.services.chat.draft import parse_accident_date
from app.services.claim_search import search_claims, search_claims_by_reference_suffix
from app.services.claim_service import (
    ClaimValidationError,
    INVALID_ACCIDENT_DATE_MESSAGE,
    append_images_to_claim,
    create_claim_shell,
    validate_accident_date,
)
from app.services.parts.estimate_builder import PRICE_DISCLAIMER
from app.services.pipeline_orchestrator import PIPELINE_STAGES


OPEN_STATUSES = {
    ClaimStatus.submitted,
    ClaimStatus.processing,
    ClaimStatus.paused_awaiting_vehicle_confirmation,
}


def _resolve_garage(db: Session, garage_name: str) -> int | None:
    name = (garage_name or "").strip()
    if not name:
        return None
    garage = db.scalar(select(Garage).where(Garage.name.ilike(name)))
    if garage is None:
        garage = Garage(name=name[:128])
        db.add(garage)
        db.flush()
    return garage.id


def find_open_duplicate(
    db: Session,
    *,
    user_id: int,
    garage_id: int | None,
    claimant_name: str | None,
    accident_date: date | None,
) -> Claim | None:
    if not garage_id or not accident_date:
        return None
    claimant = (claimant_name or "").strip()
    stmt = (
        select(Claim)
        .where(Claim.created_by == user_id)
        .where(Claim.garage_id == garage_id)
        .where(Claim.accident_date == accident_date)
        .where(Claim.status.in_(list(OPEN_STATUSES)))
        .order_by(Claim.created_at.desc())
        .limit(1)
    )
    row = db.scalar(stmt)
    if not row:
        return None
    if claimant and (row.claimant_name or "").strip().lower() != claimant.lower():
        return None
    return row


def submit_claim_external(
    db: Session,
    *,
    user_id: int,
    surveyor_name: str,
    claimant_name: str,
    garage_name: str,
    date_of_accident: str,
    garage_location: str | None = None,
) -> dict:
    """Create claim shell and return claim_no + upload_token. Does not run ML."""
    errors: list[dict] = []
    if not (surveyor_name or "").strip():
        errors.append({"field": "surveyor_name", "message": "Required"})
    if not (claimant_name or "").strip():
        errors.append({"field": "claimant_name", "message": "Required"})
    if not (garage_name or "").strip():
        errors.append({"field": "garage_name", "message": "Required"})
    if not (date_of_accident or "").strip():
        errors.append({"field": "date_of_accident", "message": "Required"})
    if errors:
        raise ValueError(("VALIDATION_ERROR", errors))

    accident = parse_accident_date(date_of_accident.strip())
    if accident is None:
        raise ValueError(
            (
                "VALIDATION_ERROR",
                [{"field": "date_of_accident", "message": INVALID_ACCIDENT_DATE_MESSAGE}],
            )
        )
    try:
        accident = validate_accident_date(accident)
    except ClaimValidationError as exc:
        raise ValueError(
            ("VALIDATION_ERROR", [{"field": "date_of_accident", "message": str(exc)}])
        ) from exc

    garage_id = _resolve_garage(db, garage_name)
    # garage_location accepted for partner compatibility; Garage model has name only.
    _ = garage_location

    dup = find_open_duplicate(
        db,
        user_id=user_id,
        garage_id=garage_id,
        claimant_name=claimant_name,
        accident_date=accident,
    )
    if dup:
        raise ValueError(
            (
                "DUPLICATE_CLAIM",
                f"An open claim already exists for this garage/claimant/date: {dup.claim_reference}",
            )
        )

    claim = create_claim_shell(
        db,
        user_id=user_id,
        garage_id=garage_id,
        surveyor_name=surveyor_name.strip(),
        claimant_name=claimant_name.strip(),
        accident_date=accident,
    )
    upload_token = mint_upload_token(claim_no=claim.claim_reference, user_id=user_id)
    from datetime import timedelta

    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    return {
        "claim_no": claim.claim_reference,
        "claim_id": claim.id,
        "upload_token": upload_token,
        "upload_token_expires_at": expires.isoformat(),
    }


async def submit_images_external(
    db: Session,
    *,
    claim: Claim,
    images: list[UploadFile],
    video: UploadFile | None = None,
    start_pipeline: bool = True,
) -> dict:
    accepted, rejected = await append_images_to_claim(
        db, claim, images=images, video=video
    )
    if accepted and start_pipeline:
        # Fire-and-forget through caller BackgroundTasks preferred; sync kick here is ok if no BG.
        pass
    cache_invalidate_prefix(f"claim:{claim.claim_reference}:")
    return {
        "claim_no": claim.claim_reference,
        "accepted": [
            {"image_id": row.id, "file_path": row.file_path, "is_video": row.is_video}
            for row in accepted
        ],
        "rejected": rejected,
        "pipeline_started": bool(accepted and start_pipeline),
    }


def get_claim_by_exact_ref(db: Session, claim_no: str, *, user_id: int | None = None) -> Claim | None:
    stmt = (
        select(Claim)
        .options(selectinload(Claim.images), selectinload(Claim.garage))
        .where(Claim.claim_reference.ilike(claim_no.strip()))
    )
    if user_id is not None:
        stmt = stmt.where(Claim.created_by == user_id)
    return db.scalar(stmt)


def resolve_claim_ref(
    db: Session,
    claim_ref: str,
    *,
    user_id: int,
) -> tuple[Claim | None, list[dict] | None]:
    """Exact or fuzzy resolve. Returns (claim, None) or (None, candidates) if ambiguous."""
    raw = (claim_ref or "").strip()
    if not raw:
        return None, None
    exact = get_claim_by_exact_ref(db, raw, user_id=user_id)
    if exact:
        return exact, None

    # Short numeric suffix: 00064
    digits = raw.replace("CLM-", "").replace("clm-", "")
    if digits.isdigit() and len(digits) <= 6:
        hits = search_claims_by_reference_suffix(db, digits, limit=8, user_id=user_id)
        if len(hits) == 1:
            claim = get_claim_by_exact_ref(db, hits[0].claim_reference, user_id=user_id)
            return claim, None
        if len(hits) > 1:
            return None, [_hit_dict(h) for h in hits[:8]]

    hits = search_claims(db, raw, limit=8, user_id=user_id)
    if not hits:
        return None, None
    if len(hits) == 1:
        claim = get_claim_by_exact_ref(db, hits[0].claim_reference, user_id=user_id)
        return claim, None
    # Multiple close candidates — don't guess
    top = hits[0].score or 0
    close = [h for h in hits if (h.score or 0) >= top - 5]
    if len(close) > 1:
        return None, [_hit_dict(h) for h in close[:8]]
    claim = get_claim_by_exact_ref(db, hits[0].claim_reference, user_id=user_id)
    return claim, None


def _hit_dict(hit) -> dict:
    return {
        "claim_no": hit.claim_reference,
        "claim_id": hit.claim_id,
        "garage_name": hit.garage_name,
        "surveyor_name": hit.surveyor_name,
        "status": hit.status,
        "score": hit.score,
    }


def claim_detail_payload(db: Session, claim: Claim) -> dict:
    cache_key = f"claim:{claim.claim_reference}:detail"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached
    events = db.scalars(
        select(PipelineEvent)
        .where(PipelineEvent.claim_id == claim.id)
        .order_by(PipelineEvent.id.asc())
    ).all()
    status = claim.status.value if hasattr(claim.status, "value") else str(claim.status)
    current_stage = events[-1].stage_key if events else None
    # Ensure images/garage loaded
    claim = db.scalar(
        select(Claim)
        .options(selectinload(Claim.images), selectinload(Claim.garage))
        .where(Claim.id == claim.id)
    ) or claim
    payload = {
        "claim_no": claim.claim_reference,
        "claim_id": claim.id,
        "status": status,
        "surveyor_name": claim.surveyor_name,
        "claimant_name": claim.claimant_name,
        "garage_name": claim.garage.name if claim.garage else None,
        "accident_date": claim.accident_date.isoformat() if claim.accident_date else None,
        "image_count": len(claim.images or []),
        "current_stage": current_stage,
        "created_at": claim.created_at.isoformat() if claim.created_at else None,
    }
    cache_set(cache_key, payload)
    return payload


def assessment_payload(db: Session, claim: Claim) -> dict:
    cache_key = f"claim:{claim.claim_reference}:assessment"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    events = db.scalars(
        select(PipelineEvent)
        .where(PipelineEvent.claim_id == claim.id)
        .order_by(PipelineEvent.id.asc())
    ).all()
    by_key = {e.stage_key: e for e in events}
    stages = []
    for key, label in PIPELINE_STAGES:
        event = by_key.get(key)
        if not event:
            stages.append(
                {"stage_key": key, "stage_label": label, "status": "pending", "detail": None}
            )
            continue
        status = event.status.value if hasattr(event.status, "value") else str(event.status)
        mapped = {
            "started": "in_progress",
            "passed": "complete",
            "failed": "failed",
            "warning": "needs_confirmation",
            "pending": "pending",
        }.get(status, status)
        stages.append(
            {
                "stage_key": key,
                "stage_label": event.stage_label or label,
                "status": mapped,
                "detail": event.detail,
                "work_seconds": event.work_seconds,
            }
        )

    vehicles = db.scalars(select(Vehicle).where(Vehicle.source_claim_id == claim.id)).all()
    vehicle_payload = [
        {
            "make": v.make,
            "model": v.model,
            "year": v.year,
            "pricing_basis": getattr(v, "pricing_basis", None),
            "identity_confirmed": getattr(v, "identity_confirmed", None),
        }
        for v in vehicles
    ]
    detections = db.scalars(
        select(DamageDetection).where(DamageDetection.claim_id == claim.id).limit(50)
    ).all()
    damage_payload = [
        {
            "part_name": d.part_name,
            "damage_type": d.damage_type.value if hasattr(d.damage_type, "value") else str(d.damage_type),
            "severity": d.severity.value if hasattr(d.severity, "value") else d.severity,
            "confidence": d.confidence_score,
        }
        for d in detections
    ]

    claim_status = claim.status.value if hasattr(claim.status, "value") else str(claim.status)
    if claim_status in {"estimate_ready"}:
        overall = "complete"
    elif claim_status in {
        "authenticity_failed",
        "review_required",
    }:
        overall = "failed"
    elif claim_status == "paused_awaiting_vehicle_confirmation":
        overall = "needs_confirmation"
    elif any(s["status"] == "in_progress" for s in stages) or claim_status in {
        "submitted",
        "processing",
    }:
        overall = "in_progress"
    else:
        overall = claim_status

    payload = {
        "claim_no": claim.claim_reference,
        "status": overall,
        "claim_status": claim_status,
        "stages": stages,
        "vehicles": vehicle_payload,
        "damage_detections": damage_payload,
    }
    cache_set(cache_key, payload)
    return payload


def estimate_payload(db: Session, claim: Claim) -> dict:
    cache_key = f"claim:{claim.claim_reference}:estimate"
    cached = cache_get(cache_key)
    if cached is not None:
        return cached

    estimate = db.scalar(select(Estimate).where(Estimate.claim_id == claim.id))
    if not estimate:
        payload = {
            "claim_no": claim.claim_reference,
            "status": "in_progress",
            "line_items": [],
            "pricing_basis": None,
            "grand_total": None,
            "disclaimer": PRICE_DISCLAIMER,
        }
        cache_set(cache_key, payload, ttl=10)
        return payload

    basis = estimate.pricing_basis
    approximate = None
    if basis == "model_fallback_priced" and estimate.fallback_source_model:
        vehicles = db.scalars(select(Vehicle).where(Vehicle.source_claim_id == claim.id)).all()
        identified = None
        if vehicles:
            v = vehicles[0]
            identified = " ".join(
                p for p in [v.make, v.model, str(v.year) if v.year else None] if p
            )
        approximate = (
            f"Approximate pricing: catalogue prices from {estimate.fallback_source_model}"
            + (f" used for identified vehicle {identified}." if identified else ".")
        )

    payload = {
        "claim_no": claim.claim_reference,
        "status": "ready",
        "line_items": estimate.line_items or [],
        "subtotal": float(estimate.subtotal or 0),
        "tax": float(estimate.tax or 0),
        "grand_total": float(estimate.grand_total or 0),
        "pricing_basis": basis,
        "fallback_source_model": estimate.fallback_source_model,
        "reason_summary": estimate.reason_summary,
        "disclaimer": PRICE_DISCLAIMER,
        "approximate_pricing_notice": approximate,
        "generated_at": estimate.generated_at.isoformat() if estimate.generated_at else None,
    }
    cache_set(cache_key, payload)
    return payload


def verify_upload_token(token: str, *, claim_no: str, user_id: int) -> None:
    try:
        data = parse_upload_token(token)
    except TokenCryptoError as exc:
        code = "UPLOAD_TOKEN_EXPIRED" if "expired" in str(exc).lower() else "UPLOAD_TOKEN_INVALID"
        raise ValueError(code) from exc
    if data.get("claim_no") != claim_no or int(data.get("user_id") or 0) != user_id:
        raise ValueError("UPLOAD_TOKEN_INVALID")
