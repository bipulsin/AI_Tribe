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
    if updates.get("kyc_mode") not in {None, KYC_MODE_MOCK, "insurer_api", "local_extraction", "eko_pan_lite"}:
        return JSONResponse({"detail": "Unknown KYC mode"}, status_code=400)
    save_settings(db, user.id, updates)
    return public_settings_view(db, user.id)


@router.post("/policy/settings/test-eko")
async def policy_test_eko(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    from app.policy.eko_runtime import eko_configured, prepare_eko_environ
    from app.policy.kyc import EkoKycProvider
    from app.policy.vehicle import EkoVahanProvider

    prepare_eko_environ()
    if not eko_configured():
        return {
            "ok": False,
            "eko_connected": False,
            "note": "EKO credentials are incomplete. Set EKO_ACCESS_KEY, EKO_DEVELOPER_KEY, and EKO_INITIATOR_ID.",
            "vehicle": None,
            "pan": None,
        }

    vehicle_probe: dict = {}
    pan_probe: dict = {}
    try:
        v = EkoVahanProvider().lookup("HR26DA8398")
        data = v.raw_payload.get("data") if isinstance(v.raw_payload, dict) else {}
        snippet = {}
        if isinstance(data, dict):
            for key in ("make", "model", "owner", "rc_status", "fuel_type", "blacklist_status"):
                if data.get(key) is not None:
                    snippet[key] = data.get(key)
        vehicle_probe = {
            "response_status_id": v.response_status_id,
            "message": v.user_notice or v.error or ("ok" if v.source == "live_api" else v.source_label),
            "source": v.source,
            "source_label": v.source_label,
            "client_ref_id": v.client_ref_id,
            "data_snippet": snippet,
            "make": v.make,
            "model": v.model,
        }
    except Exception as exc:
        vehicle_probe = {"error": type(exc).__name__, "message": "Vehicle RC test failed"}

    try:
        pan_result = EkoKycProvider().validate_pan(
            pan_number="ABCDE1234F",
            name="Test User",
            dob="1990-01-01",
            session_id="settings-test",
            attempt_number=1,
        )
        pan_probe = {
            "response_status_id": pan_result.response_status_id,
            "message": pan_result.user_notice or pan_result.reason or ("ok" if pan_result.valid else "not valid"),
            "validation_mode": pan_result.mode,
            "label": pan_result.label,
            "demo_mode": pan_result.demo_mode,
            "name_match": pan_result.name_match,
            "dob_match": pan_result.dob_match,
            "pan_status": pan_result.pan_status,
            "id_masked": pan_result.id_masked,
            "client_ref_id": pan_result.client_ref_id,
        }
    except Exception as exc:
        pan_probe = {"error": type(exc).__name__, "message": "PAN Lite test failed"}

    live_ok = vehicle_probe.get("source") == "live_api" or pan_probe.get("validation_mode") == "eko_pan_lite"
    return {
        "ok": True,
        "eko_connected": True,
        "live": live_ok,
        "vehicle": vehicle_probe,
        "pan": pan_probe,
        "note": "Test used HR26DA8398 and ABCDE1234F only. Credentials are never returned.",
    }
