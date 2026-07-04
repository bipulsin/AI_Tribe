"""Claim submission and detail routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from starlette.datastructures import UploadFile

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Claim, PipelineEvent
from app.models.enums import ClaimStatus
from app.services.claim_service import ClaimValidationError, create_claim_with_uploads
from app.services.pipeline_orchestrator import PIPELINE_STAGES, ensure_pipeline_started

router = APIRouter(tags=["claims"])
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))


@router.get("/claims/new", response_class=HTMLResponse)
async def claim_new(request: Request):
    return templates.TemplateResponse(
        "claim_new.html",
        {
            "request": request,
            "username": request.session.get("username", ""),
            "full_name": request.session.get("full_name", ""),
            "max_images": settings.max_images_per_claim,
            "max_upload_mb": settings.max_upload_mb,
        },
    )


@router.post("/claims")
async def create_claim(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user_id = request.session.get("user_id")
    form = await request.form()

    images = [
        item
        for item in form.getlist("images")
        if isinstance(item, UploadFile) and item.filename
    ]
    video_field = form.get("video")
    video = (
        video_field
        if isinstance(video_field, UploadFile) and video_field.filename
        else None
    )

    try:
        claim = await create_claim_with_uploads(
            db,
            user_id=user_id,
            images=images,
            video=video,
        )
    except ClaimValidationError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    background_tasks.add_task(ensure_pipeline_started, claim.id)

    return JSONResponse(
        {
            "claim_id": claim.id,
            "claim_reference": claim.claim_reference,
            "redirect": f"/claims/{claim.id}/processing",
        }
    )


@router.get("/claims/{claim_id}/processing", response_class=HTMLResponse)
async def claim_processing(
    claim_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    claim = db.scalar(
        select(Claim)
        .options(
            selectinload(Claim.images),
            selectinload(Claim.pipeline_events),
        )
        .where(Claim.id == claim_id)
    )
    def _bootstrap_json(payload: dict) -> str:
        # Escape < so embedding in <script type="application/json"> is safe.
        return json.dumps(payload).replace("<", "\\u003c")

    if not claim:
        return templates.TemplateResponse(
            "claim_processing.html",
            {
                "request": request,
                "claim": None,
                "error": "Claim not found.",
                "bootstrap_json": _bootstrap_json(
                    {
                        "claimId": None,
                        "stages": [],
                        "initialEvents": [],
                        "claimStatus": None,
                    }
                ),
            },
            status_code=404,
        )

    if claim.created_by != request.session.get("user_id"):
        return templates.TemplateResponse(
            "claim_processing.html",
            {
                "request": request,
                "claim": None,
                "error": "You do not have access to this claim.",
                "bootstrap_json": _bootstrap_json(
                    {
                        "claimId": None,
                        "stages": [],
                        "initialEvents": [],
                        "claimStatus": None,
                    }
                ),
            },
            status_code=403,
        )

    if claim.status in {ClaimStatus.submitted, ClaimStatus.processing}:
        background_tasks.add_task(ensure_pipeline_started, claim.id)

    events = sorted(claim.pipeline_events, key=lambda e: e.id)
    initial_events = [
        {
            "id": event.id,
            "claim_id": event.claim_id,
            "stage_key": event.stage_key,
            "stage_label": event.stage_label,
            "status": event.status.value if hasattr(event.status, "value") else event.status,
            "detail": event.detail,
            "work_seconds": event.work_seconds,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
        for event in events
    ]

    # Full chain rendered on load; SSE only transitions status/timers.
    stages = [
        {
            "key": key,
            "label": label,
            "status": "pending",
            "detail": None,
            "timerLabel": "",
        }
        for key, label in PIPELINE_STAGES
    ]

    return templates.TemplateResponse(
        "claim_processing.html",
        {
            "request": request,
            "claim": claim,
            "error": None,
            "username": request.session.get("username", ""),
            "full_name": request.session.get("full_name", ""),
            "bootstrap_json": _bootstrap_json(
                {
                    "claimId": claim.id,
                    "stages": stages,
                    "initialEvents": initial_events,
                    "claimStatus": claim.status.value,
                }
            ),
        },
    )
