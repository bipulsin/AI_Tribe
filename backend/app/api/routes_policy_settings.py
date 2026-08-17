"""Policy module settings API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import session_user
from app.core.database import get_db
from app.policy.constants import KYC_MODE_MOCK
from app.policy.settings_store import load_settings, public_settings_view, save_settings
from app.policy.vehicle import lookup_vehicle

router = APIRouter(tags=["policy-settings"])


class PolicySettingsPayload(BaseModel):
    force_demo_fallback: bool | None = None
    kyc_mode: str | None = Field(default=None, max_length=64)
    quotes_randomized: bool | None = None
    premium_floor_a: float | None = None
    premium_floor_b: float | None = None
    premium_floor_c: float | None = None
    watermark_text: str | None = Field(default=None, max_length=120)
    show_demo_labels: bool | None = None


@router.get("/policy/settings.json")
async def policy_settings_json(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return public_settings_view(db, user.id)


@router.post("/policy/settings")
async def policy_settings_save(
    payload: PolicySettingsPayload, request: Request, db: Session = Depends(get_db)
):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    updates = payload.model_dump(exclude_none=True)
    if "show_demo_labels" in updates:
        updates["show_demo_labels"] = True
    if updates.get("kyc_mode") not in {None, KYC_MODE_MOCK, "insurer_api", "local_extraction"}:
        return JSONResponse({"detail": "Unknown KYC mode"}, status_code=400)
    save_settings(db, user.id, updates)
    return public_settings_view(db, user.id)


@router.post("/policy/settings/test-eko")
async def policy_test_eko(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    stored = load_settings(db, user.id)
    result = lookup_vehicle("MH02AB1234", force_fallback=bool(stored.get("force_demo_fallback")))
    live = result.source == "live_api"
    return {
        "ok": True,
        "live": live,
        "source": result.source,
        "source_label": result.source_label,
        "make": result.make,
        "model": result.model,
        "error": result.error,
        "note": (
            "Live Vahan Lookup succeeded."
            if live
            else "EKO live call was not used or failed; Demo Data — Fallback was returned. "
            "Live lookup also needs EKO_DEVELOPER_KEY and EKO_INITIATOR_ID."
        ),
    }
