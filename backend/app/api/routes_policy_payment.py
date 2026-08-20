"""Simulated payment processing for the policy booking flow."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import session_user
from app.core.database import get_db
from app.policy.constants import SESSION_COOKIE
from app.policy.flow import (
    PaymentFlowError,
    get_booking_by_session,
    process_simulated_payment,
    serialize_booking,
)

router = APIRouter(tags=["policy-payment"])


async def _payload(request: Request) -> dict:
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    form = await request.form()
    return {str(key): form.get(key) for key in form.keys()}


@router.post("/policy/payment/process")
async def policy_payment_process(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    body = await _payload(request)
    session_id = (body.get("session_id") or request.cookies.get(SESSION_COOKIE) or "").strip()
    if not session_id:
        return JSONResponse({"detail": "A session_id is required."}, status_code=400)
    booking = get_booking_by_session(db, session_id, user.id)
    if not booking:
        return JSONResponse({"detail": "No active booking"}, status_code=404)
    try:
        booking = process_simulated_payment(
            db,
            booking,
            user.id,
            payment_method=str(body.get("selected_payment_method") or body.get("payment_method") or ""),
            card_holder_name=body.get("card_holder_name"),
            card_number=body.get("card_number") or body.get("card_number_masked"),
            expiry=body.get("expiry") or body.get("expiry_masked"),
            cvv=body.get("cvv"),
        )
    except PaymentFlowError as exc:
        payload: dict = {"detail": str(exc)}
        if exc.status_code >= 500:
            latest = get_booking_by_session(db, session_id, user.id)
            if latest:
                payload.update(serialize_booking(latest))
        return JSONResponse(payload, status_code=exc.status_code)
    return serialize_booking(booking)
