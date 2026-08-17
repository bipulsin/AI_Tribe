"""Standalone KYC validation endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import session_user
from app.core.database import get_db
from app.policy.constants import SESSION_COOKIE
from app.policy.flow import get_booking_by_session, handle_user_message, serialize_booking
from app.policy.kyc import MockInsurerTaggedProvider
from app.policy.settings_store import load_settings, resolved_kyc_mode

router = APIRouter(tags=["policy-kyc"])


class KycPayload(BaseModel):
    id_type: str = Field(default="PAN", max_length=16)
    id_number: str = Field(default="", max_length=32)


@router.post("/policy/kyc/validate")
async def policy_kyc_validate(payload: KycPayload, request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    session_id = request.cookies.get(SESSION_COOKIE)
    booking = get_booking_by_session(db, session_id, user.id) if session_id else None
    if booking:
        handle_user_message(db, booking, payload.id_type, user.id)
        booking = get_booking_by_session(db, session_id, user.id)
        if booking:
            booking = handle_user_message(db, booking, payload.id_number, user.id)
            return serialize_booking(booking)
    stored = load_settings(db, user.id)
    mode, warning = resolved_kyc_mode(stored)
    result = MockInsurerTaggedProvider().validate(
        id_type=payload.id_type,
        id_number=payload.id_number,
        attempt_number=1,
    )
    return {
        "valid": result.valid,
        "label": result.label,
        "id_masked": result.id_masked,
        "reason": result.reason,
        "mode": mode,
        "warning": warning,
        "demo_mode": True,
    }
