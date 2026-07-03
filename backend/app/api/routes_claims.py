"""Claim routes — minimal protected landing in Milestone 2; upload in Milestone 3."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.config import get_settings

router = APIRouter(tags=["claims"])
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))


@router.get("/claims/new", response_class=HTMLResponse)
async def claim_new(request: Request):
    """Post-login landing. Full upload zone lands in Milestone 3."""
    return templates.TemplateResponse(
        "claim_new.html",
        {
            "request": request,
            "username": request.session.get("username", ""),
            "full_name": request.session.get("full_name", ""),
        },
    )
