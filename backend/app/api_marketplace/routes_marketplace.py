"""Session-authenticated marketplace UI and management APIs."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api_marketplace.catalog import DEFAULT_VALIDITY_DAYS, VALIDITY_DAYS
from app.api_marketplace.crypto import TokenCryptoError
from app.api_marketplace.deps import client_ip
from app.api_marketplace.subscriptions import (
    catalog_with_subscriptions,
    create_chain,
    delete_chain,
    ensure_default_subscriptions,
    list_chains,
    set_subscription,
)
from app.api_marketplace.tokens import (
    current_token,
    issue_token,
    reveal_token,
    token_public_view,
)
from app.core.config import get_settings
from app.core.database import get_db

router = APIRouter(tags=["api-marketplace"])
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.templates_dir))


def _user_id(request: Request) -> int | None:
    return request.session.get("user_id")


@router.get("/settings/api-marketplace", response_class=HTMLResponse)
async def api_marketplace_page(request: Request, db: Session = Depends(get_db)):
    user_id = _user_id(request)
    if user_id:
        ensure_default_subscriptions(db, user_id)
    token = current_token(db, user_id) if user_id else None
    bootstrap = {
        "validityOptions": list(VALIDITY_DAYS),
        "defaultValidity": DEFAULT_VALIDITY_DAYS,
        "tokenView": token_public_view(token),
        "catalog": catalog_with_subscriptions(db, user_id) if user_id else [],
        "chains": list_chains(db, user_id) if user_id else [],
        "baseUrl": (
            __import__("os")
            .environ.get("APP_PUBLIC_URL", "https://tribe.tradentical.com")
            .rstrip("/")
        ),
    }
    return templates.TemplateResponse(
        "api_marketplace.html",
        {
            "request": request,
            "username": request.session.get("username", ""),
            "full_name": request.session.get("full_name", "") or "",
            "bootstrap": bootstrap,
        },
    )


class TokenIssueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validity_days: int = DEFAULT_VALIDITY_DAYS


@router.post("/api/marketplace/token")
async def marketplace_issue_token(
    body: TokenIssueBody,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = _user_id(request)
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    try:
        row, plain = issue_token(
            db,
            user_id=user_id,
            validity_days=body.validity_days,
            ip_address=client_ip(request),
        )
    except (ValueError, TokenCryptoError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    view = token_public_view(row)
    return {"token": plain, "token_view": view}


@router.post("/api/marketplace/token/reveal")
async def marketplace_reveal_token(request: Request, db: Session = Depends(get_db)):
    user_id = _user_id(request)
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    try:
        row, plain = reveal_token(db, user_id=user_id, ip_address=client_ip(request))
    except (ValueError, TokenCryptoError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return {"token": plain, "token_view": token_public_view(row)}


@router.get("/api/marketplace/token")
async def marketplace_token_status(request: Request, db: Session = Depends(get_db)):
    user_id = _user_id(request)
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return {"token_view": token_public_view(current_token(db, user_id))}


class SubscribeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_name: str
    enabled: bool = True


@router.post("/api/marketplace/subscribe")
async def marketplace_subscribe(
    body: SubscribeBody,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = _user_id(request)
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    try:
        row = set_subscription(
            db, user_id=user_id, api_name=body.api_name, enabled=body.enabled
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return {
        "api_name": row.api_name,
        "enabled": row.enabled,
        "catalog": catalog_with_subscriptions(db, user_id),
    }


class ChainBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chain_name: str = Field(min_length=1, max_length=128)
    follow_on: list[str] = Field(default_factory=list)


@router.get("/api/marketplace/chains")
async def marketplace_list_chains(request: Request, db: Session = Depends(get_db)):
    user_id = _user_id(request)
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return {"chains": list_chains(db, user_id)}


@router.post("/api/marketplace/chains")
async def marketplace_create_chain(
    body: ChainBody,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = _user_id(request)
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    try:
        create_chain(
            db, user_id=user_id, chain_name=body.chain_name, follow_on=body.follow_on
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return {"chains": list_chains(db, user_id)}


@router.delete("/api/marketplace/chains/{chain_id}")
async def marketplace_delete_chain(
    chain_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    user_id = _user_id(request)
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    try:
        delete_chain(db, user_id=user_id, chain_id=chain_id)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return {"chains": list_chains(db, user_id)}


@router.post("/api/marketplace/jobs/token-reminders")
async def marketplace_run_token_reminders(request: Request, db: Session = Depends(get_db)):
    """Admin/ops endpoint to trigger daily expiry reminder emails."""
    from app.api.deps import require_admin
    from app.api_marketplace.tokens import process_token_expiry_reminders

    admin = require_admin(request, db)
    if isinstance(admin, JSONResponse):
        return admin
    return process_token_expiry_reminders(db)
