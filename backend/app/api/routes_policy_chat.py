"""Policy chat message endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import session_user
from app.api.routes_policy import attach_session_cookie
from app.core.database import get_db
from app.policy.constants import SESSION_COOKIE
from app.policy.flow import get_booking_by_session, handle_user_message, serialize_booking, start_booking

router = APIRouter(tags=["policy-chat"])


class PolicyMessagePayload(BaseModel):
    text: str = Field(default="", max_length=4000)


@router.post("/policy/chat/start")
async def policy_chat_start(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    booking = start_booking(db, user.id)
    response = JSONResponse(serialize_booking(booking))
    attach_session_cookie(response, booking.session_id)
    return response


@router.post("/policy/chat/message")
async def policy_chat_message(
    request: Request,
    payload: PolicyMessagePayload,
    db: Session = Depends(get_db),
):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    session_id = request.cookies.get(SESSION_COOKIE)
    booking = get_booking_by_session(db, session_id, user.id) if session_id else None
    if booking is None:
        booking = start_booking(db, user.id)
    booking = handle_user_message(db, booking, payload.text, user.id)
    response = JSONResponse(serialize_booking(booking))
    attach_session_cookie(response, booking.session_id)
    return response
