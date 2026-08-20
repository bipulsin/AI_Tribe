"""Standalone vehicle lookup endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import session_user
from app.core.database import get_db
from app.policy.constants import SESSION_COOKIE
from app.policy.extraction import is_valid_registration, normalize_registration
from app.policy.flow import get_booking_by_session
from app.policy.settings_store import load_settings
from app.policy.vehicle import lookup_vehicle

router = APIRouter(tags=["policy-vehicle"])


@router.get("/policy/vehicle/lookup")
async def policy_vehicle_lookup(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    registration = (request.query_params.get("registration") or "").strip()
    if not is_valid_registration(registration):
        return JSONResponse({"detail": "Invalid registration number"}, status_code=400)
    stored = load_settings(db, user.id)
    result = lookup_vehicle(
        normalize_registration(registration),
        force_fallback=bool(stored.get("force_demo_fallback")),
        session_id=request.cookies.get(SESSION_COOKIE),
    )
    session_id = request.cookies.get(SESSION_COOKIE)
    booking = get_booking_by_session(db, session_id, user.id) if session_id else None
    return {
        "registration_number": result.registration_number,
        "make": result.make,
        "model": result.model,
        "year": result.year,
        "color": result.color,
        "fuel_type": result.fuel_type,
        "owner_name": result.owner_name,
        "source": result.source,
        "source_label": result.source_label,
        "booking_id": str(booking.id) if booking else None,
    }
