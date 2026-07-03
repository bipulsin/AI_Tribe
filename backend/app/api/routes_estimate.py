"""Survey estimate sheet routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Claim
from app.services.parts import estimate_builder

router = APIRouter(tags=["estimate"])
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))


@router.get("/claims/{claim_id}/estimate", response_class=HTMLResponse)
async def claim_estimate(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    claim = db.scalar(
        select(Claim)
        .options(
            selectinload(Claim.images),
            selectinload(Claim.damage_detections),
            selectinload(Claim.estimate),
            selectinload(Claim.fraud_signals),
            selectinload(Claim.vehicles),
            selectinload(Claim.pipeline_events),
        )
        .where(Claim.id == claim_id)
    )

    error = None
    if not claim:
        error = "Claim not found."
    elif claim.created_by != request.session.get("user_id"):
        error = "You do not have access to this claim."
        claim = None

    if error or not claim:
        return templates.TemplateResponse(
            "claim_estimate.html",
            {"request": request, "claim": None, "error": error},
            status_code=404 if error == "Claim not found." else 403,
        )

    estimate = claim.estimate
    if not estimate:
        estimate = estimate_builder.persist_estimate(db, claim.id)
        db.refresh(claim)

    vehicle = claim.vehicles[0] if claim.vehicles else None
    fraud_signals = sorted(claim.fraud_signals, key=lambda s: s.id)
    detections = sorted(claim.damage_detections, key=lambda d: d.id)
    line_items = estimate.line_items or []
    confidences = [float(d.confidence_score) for d in detections]
    max_confidence = max(confidences) if confidences else None

    catalogue_vehicle_label = None
    for item in line_items:
        note = item.get("match_note") or ""
        if " · " in note:
            catalogue_vehicle_label = note.split(" · ", 1)[0].strip()
            break
    if not catalogue_vehicle_label and vehicle and vehicle.make:
        catalogue_vehicle_label = f"{vehicle.make} {vehicle.model or ''}".strip()

    return templates.TemplateResponse(
        "claim_estimate.html",
        {
            "request": request,
            "claim": claim,
            "error": None,
            "estimate": estimate,
            "vehicle": vehicle,
            "line_items": line_items,
            "fraud_signals": fraud_signals,
            "detections": detections,
            "max_confidence": max_confidence,
            "catalogue_vehicle_label": catalogue_vehicle_label,
            "username": request.session.get("username", ""),
            "full_name": request.session.get("full_name", ""),
        },
    )
