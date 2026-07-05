"""Lab VMMR labeling routes (VehiDE only; admin-only)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import get_settings
from app.core.database import get_db
from app.models import VmmrLabLabel
from app.services.vmmr.lab_labeling.constants import LAB_LABEL_NOTICE, VEHIDE_RAW_ROOT
from app.services.vmmr.lab_labeling.dataset_store import save_confirmed_label
from app.services.vmmr.lab_labeling.vehide_queue import (
    build_overlap_queue,
    ensure_guess,
    import_overlap_queue,
    labeling_stats,
)
from app.services.vmmr.vehicle_confirmation import catalog_makes_models

router = APIRouter(tags=["lab-labeling"])
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))


def _allowed_lab_image(path: Path) -> bool:
    resolved = path.resolve()
    roots = []
    for raw in (
        VEHIDE_RAW_ROOT,
        Path("/mnt/ml-scratch/vehide/raw"),
        Path("/mnt/ml-scratch/vmmr_labeling"),
    ):
        if raw.exists():
            roots.append(raw.resolve())
    return any(resolved.is_relative_to(root) for root in roots)


@router.get("/lab/vmmr-labeling", response_class=HTMLResponse)
async def lab_vmmr_labeling_page(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    if isinstance(user, JSONResponse):
        return user
    return templates.TemplateResponse(
        "lab_vmmr_labeling.html",
        {
            "request": request,
            "username": request.session.get("username", ""),
            "lab_notice": LAB_LABEL_NOTICE,
        },
    )


@router.get("/api/lab/vmmr-labeling/stats")
async def lab_labeling_stats(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    if isinstance(user, JSONResponse):
        return user
    return labeling_stats(db)


@router.get("/api/lab/vmmr-labeling/next")
async def lab_labeling_next(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    if isinstance(user, JSONResponse):
        return user

    row = db.scalar(
        select(VmmrLabLabel)
        .where(VmmrLabLabel.status == "pending")
        .order_by(VmmrLabLabel.id.asc())
        .limit(1)
    )
    if row is None:
        return {"item": None, "lab_notice": LAB_LABEL_NOTICE}

    row = ensure_guess(db, row)
    return {
        "item": {
            "id": row.id,
            "source_dataset": row.source_dataset,
            "damage_hint": row.damage_hint,
            "image_url": f"/api/lab/vmmr-labeling/images/{row.id}",
            "suggested_make": row.suggested_make,
            "suggested_model": row.suggested_model,
            "suggested_confidence": row.suggested_confidence,
            "guess_source": row.guess_source,
            "guess_detail": row.guess_detail,
            "alternatives": row.suggested_alternatives or [],
            "license_tag": row.license_tag,
        },
        "catalog": catalog_makes_models(db),
        "lab_notice": LAB_LABEL_NOTICE,
    }


@router.get("/api/lab/vmmr-labeling/images/{label_id}")
async def lab_labeling_image(
    label_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, JSONResponse):
        return user

    row = db.get(VmmrLabLabel, label_id)
    if not row:
        return JSONResponse({"detail": "Not found"}, status_code=404)

    path = Path(row.image_path)
    if not path.is_file() or not _allowed_lab_image(path):
        return JSONResponse({"detail": "Image unavailable"}, status_code=404)

    return FileResponse(path)


@router.post("/api/lab/vmmr-labeling/{label_id}/confirm")
async def lab_labeling_confirm(
    label_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, JSONResponse):
        return user

    row = db.get(VmmrLabLabel, label_id)
    if not row or row.status != "pending":
        return JSONResponse({"detail": "Label not pending"}, status_code=400)

    body = await request.json()
    make = (body.get("make") or "").strip()
    model = (body.get("model") or "").strip()
    if not make or not model:
        return JSONResponse({"detail": "Make and model required"}, status_code=400)

    row.confirmed_make = make
    row.confirmed_model = model
    row.status = "confirmed"
    row.labeled_by = user.id
    row.labeled_at = datetime.now(timezone.utc)
    scratch = save_confirmed_label(row, labeled_by=user.id)
    row.scratch_copy_path = scratch
    db.commit()

    return {
        "id": row.id,
        "status": row.status,
        "confirmed_make": make,
        "confirmed_model": model,
        "scratch_copy_path": scratch,
        "lab_notice": LAB_LABEL_NOTICE,
    }


@router.post("/api/lab/vmmr-labeling/{label_id}/skip")
async def lab_labeling_skip(
    label_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, JSONResponse):
        return user

    row = db.get(VmmrLabLabel, label_id)
    if not row or row.status != "pending":
        return JSONResponse({"detail": "Label not pending"}, status_code=400)

    row.status = "skipped"
    row.labeled_by = user.id
    row.labeled_at = datetime.now(timezone.utc)
    db.commit()
    return {"id": row.id, "status": row.status}


@router.post("/api/lab/vmmr-labeling/build-overlap-queue")
async def lab_build_overlap_queue(
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_admin(request, db)
    if isinstance(user, JSONResponse):
        return user

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    split = payload.get("split", "val")
    limit = int(payload.get("limit") or 0)
    return build_overlap_queue(db, split=split or None, limit=limit)


@router.post("/api/lab/vmmr-labeling/import-queue")
async def lab_import_queue(request: Request, db: Session = Depends(get_db)):
    user = require_admin(request, db)
    if isinstance(user, JSONResponse):
        return user

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    refresh = bool(payload.get("refresh_guess"))
    return import_overlap_queue(db, refresh_guess=refresh)
