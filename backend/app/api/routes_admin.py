"""Admin and catalog helper routes."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User
from app.services.vmmr.vehicle_confirmation import (
    apply_manual_vehicle_identity,
    catalog_makes_models,
    correction_queue_summary,
)
from app.services.pipeline_orchestrator import resume_pipeline_after_vehicle_confirmation

router = APIRouter(tags=["admin"])


@router.get("/api/catalog/vehicles")
async def list_catalog_vehicles(db: Session = Depends(get_db)):
    return {"makes": catalog_makes_models(db)}


@router.get("/api/admin/vmmr-corrections/summary")
async def vmmr_corrections_summary(
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    user = db.get(User, user_id)
    if not user or user.role != "admin":
        return JSONResponse({"detail": "Admin only"}, status_code=403)
    return correction_queue_summary(db)


@router.post("/api/pipeline/{claim_id}/confirm-vehicle")
async def confirm_vehicle(
    claim_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    from app.models import Claim
    from app.models.enums import ClaimStatus

    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    claim = db.get(Claim, claim_id)
    if not claim or claim.created_by != user_id:
        return JSONResponse({"detail": "Claim not found"}, status_code=404)

    if claim.status != ClaimStatus.paused_awaiting_vehicle_confirmation:
        return JSONResponse(
            {"detail": "Claim is not awaiting vehicle confirmation"},
            status_code=400,
        )

    body = await request.json()
    make = (body.get("make") or "").strip()
    model = (body.get("model") or "").strip()
    if not make or not model:
        return JSONResponse(
            {"detail": "Make and model are required"},
            status_code=400,
        )

    apply_manual_vehicle_identity(
        db,
        claim_id=claim_id,
        make=make,
        model=model,
        submitted_by=user_id,
    )
    claim.status = ClaimStatus.processing
    db.commit()

    background_tasks.add_task(resume_pipeline_after_vehicle_confirmation, claim_id)

    return JSONResponse(
        {
            "claim_id": claim_id,
            "status": claim.status.value,
            "make": make,
            "model": model,
            "detail": "Vehicle confirmed. Resuming assessment.",
        }
    )
