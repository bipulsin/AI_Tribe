"""Estimate routes — placeholder until Milestone 6."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import Claim

router = APIRouter(tags=["estimate"])
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))


@router.get("/claims/{claim_id}/estimate", response_class=HTMLResponse)
async def claim_estimate(
    claim_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    claim = db.get(Claim, claim_id)
    error = None
    if not claim:
        error = "Claim not found."
    elif claim.created_by != request.session.get("user_id"):
        error = "You do not have access to this claim."
        claim = None

    return templates.TemplateResponse(
        "claim_estimate.html",
        {
            "request": request,
            "claim": claim,
            "error": error,
        },
        status_code=404 if error and not claim else 200,
    )
