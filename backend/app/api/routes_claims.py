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
from app.api.deps import session_user, user_can_access_claim
from app.core.database import get_db
from app.models import Claim, Garage, LlmAssistLog, PipelineEvent, Vehicle
from app.models.enums import ClaimStatus
from app.services.claim_search import search_claims
from app.services.claim_service import ClaimValidationError, create_claim_with_uploads
from app.services.fraud.fraud_graph import claim_network_view
from app.services.pipeline_orchestrator import ensure_pipeline_started
from app.services.vmmr.vehicle_confirmation import catalog_makes_models

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


@router.get("/api/claims/search", response_class=HTMLResponse)
async def claims_search(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
):
    query = (q or "").strip()
    hits = search_claims(db, query) if query else []
    return templates.TemplateResponse(
        "partials/claim_search_results.html",
        {
            "request": request,
            "query": query,
            "hits": hits,
            "searched": bool(query),
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
    accident_raw = (form.get("accident_date") or "").strip()
    accident_date = None
    if accident_raw:
        from app.services.chat.draft import parse_accident_date
        from app.services.claim_service import (
            INVALID_ACCIDENT_DATE_MESSAGE,
            validate_accident_date,
        )

        accident_date = parse_accident_date(accident_raw)
        if accident_date is None:
            return JSONResponse({"detail": INVALID_ACCIDENT_DATE_MESSAGE}, status_code=400)
        try:
            accident_date = validate_accident_date(accident_date)
        except ClaimValidationError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)

    try:
        claim = await create_claim_with_uploads(
            db,
            user_id=user_id,
            images=images,
            video=video,
            garage_id=garage_id,
            surveyor_name=surveyor_name or None,
            claimant_name=claimant_name or None,
            accident_date=accident_date,
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
    embed = str(request.query_params.get("embed") or "").lower() in {"1", "true", "yes"}
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
                "embed": embed,
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

    if not user_can_access_claim(session_user(request, db), claim):
        return templates.TemplateResponse(
            "claim_processing.html",
            {
                "request": request,
                "claim": None,
                "error": "You do not have access to this claim.",
                "embed": embed,
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

    # Stages append incrementally via SSE; do not pre-render the full chain.
    stages: list[dict] = []

    network = claim_network_view(db, claim)
    fraud_assist = db.scalar(
        select(LlmAssistLog)
        .where(
            LlmAssistLog.claim_id == claim.id,
            LlmAssistLog.stage == "fraud_scoring",
        )
        .order_by(LlmAssistLog.id.desc())
    )
    vehicle = db.scalar(select(Vehicle).where(Vehicle.source_claim_id == claim.id))
    vehicle_llm_suggest = None
    if vehicle and vehicle.llm_suggest_make:
        vehicle_llm_suggest = {
            "make": vehicle.llm_suggest_make,
            "model": vehicle.llm_suggest_model,
            "provider": vehicle.llm_suggest_provider,
        }
    network_payload = {
        "clear": network.clear,
        "caption": network.caption,
        "flaggedNodeIds": network.flagged_node_ids,
        "llmInterpretation": fraud_assist.summary if fraud_assist else None,
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
                    "catalogMakes": catalog_makes_models(db),
                    "vehicleLlmSuggest": vehicle_llm_suggest,
                }
            ),
            "embed": embed,
        },
    )
