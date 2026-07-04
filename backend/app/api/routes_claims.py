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
from app.models import Claim, Garage, PipelineEvent
from app.models.enums import ClaimStatus
from app.services.claim_service import ClaimValidationError, create_claim_with_uploads
from app.services.fraud.fraud_graph import claim_network_view
from app.services.pipeline_orchestrator import PIPELINE_STAGES, ensure_pipeline_started

router = APIRouter(tags=["claims"])
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))


@router.get("/claims/new", response_class=HTMLResponse)
async def claim_new(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        "claim_new.html",
        {
            "request": request,
            "username": request.session.get("username", ""),
            "full_name": request.session.get("full_name", "") or "",
            "max_images": settings.max_images_per_claim,
            "max_upload_mb": settings.max_upload_mb,
        },
    )


@router.get("/api/suggest/garages", response_class=HTMLResponse)
async def suggest_garages(
    request: Request,
    q: str = "",
    garage_name: str = "",
    db: Session = Depends(get_db),
):
    query = (q or garage_name or "").strip()
    stmt = select(Garage.name).order_by(Garage.name.asc()).limit(8)
    if query:
        stmt = (
            select(Garage.name)
            .where(Garage.name.ilike(f"%{query}%"))
            .order_by(Garage.name.asc())
            .limit(8)
        )
    names = list(db.scalars(stmt).all())
    return templates.TemplateResponse(
        "partials/suggest_list.html",
        {
            "request": request,
            "names": names,
            "field": "garageName",
            "empty": not names and bool(query),
        },
    )


@router.get("/api/suggest/surveyors", response_class=HTMLResponse)
async def suggest_surveyors(
    request: Request,
    q: str = "",
    surveyor_name: str = "",
    db: Session = Depends(get_db),
):
    query = (q or surveyor_name or "").strip()
    stmt = (
        select(Claim.surveyor_name)
        .where(Claim.surveyor_name.is_not(None))
        .where(Claim.surveyor_name != "")
        .distinct()
        .order_by(Claim.surveyor_name.asc())
        .limit(8)
    )
    if query:
        stmt = (
            select(Claim.surveyor_name)
            .where(Claim.surveyor_name.is_not(None))
            .where(Claim.surveyor_name.ilike(f"%{query}%"))
            .distinct()
            .order_by(Claim.surveyor_name.asc())
            .limit(8)
        )
    names = [name for name in db.scalars(stmt).all() if name]
    return templates.TemplateResponse(
        "partials/suggest_list.html",
        {
            "request": request,
            "names": names,
            "field": "surveyorName",
            "empty": not names and bool(query),
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
    garage_name = (form.get("garage_name") or "").strip()
    surveyor_name = (form.get("surveyor_name") or "").strip()
    garage_id = None
    if garage_name:
        garage = db.scalar(select(Garage).where(Garage.name.ilike(garage_name)))
        if garage is None:
            garage = Garage(name=garage_name)
            db.add(garage)
            db.flush()
        garage_id = garage.id

    claimant_name = (request.session.get("full_name") or request.session.get("username") or "").strip()

    try:
        claim = await create_claim_with_uploads(
            db,
            user_id=user_id,
            images=images,
            video=video,
            garage_id=garage_id,
            surveyor_name=surveyor_name or None,
            claimant_name=claimant_name or None,
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
            selectinload(Claim.garage),
            selectinload(Claim.creator),
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

    network = claim_network_view(db, claim)
    network_payload = {
        "clear": network.clear,
        "caption": network.caption,
        "flaggedNodeIds": network.flagged_node_ids,
        "nodes": [
            {
                "id": node.id,
                "label": node.label,
                "kind": node.kind,
                "flagged": node.flagged,
                "degree": node.degree,
            }
            for node in network.nodes
        ],
        "edges": [
            {
                "from": edge.source,
                "to": edge.target,
                "title": edge.claim_reference,
            }
            for edge in network.edges
        ],
    }

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
                    "network": network_payload,
                }
            ),
        },
    )
