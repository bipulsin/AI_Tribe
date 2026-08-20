"""Policy issuance and PDF download (illustrative artefact)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import session_user
from app.core.database import get_db
from app.core.roles import can_view_all_claims
from app.policy.constants import SESSION_COOKIE
from app.policy.flow import get_booking_by_session, handle_user_message, serialize_booking
from app.policy.models import PolicyIssuedPolicy

router = APIRouter(tags=["policy-issue"])


@router.post("/policy/issue")
async def policy_issue(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    session_id = request.cookies.get(SESSION_COOKIE)
    booking = get_booking_by_session(db, session_id, user.id) if session_id else None
    if not booking:
        return JSONResponse({"detail": "No active booking"}, status_code=404)
    if booking.current_step == "select_quote" and any(q.selected for q in booking.quotes):
        booking.current_step = "initiate_payment"
    if booking.current_step == "initiate_payment":
        return JSONResponse(
            {"detail": "Complete the simulated payment in chat before issuance."},
            status_code=400,
        )
    booking = handle_user_message(db, booking, "issue", user.id)
    return serialize_booking(booking)


@router.get("/policy/document/{policy_id}")
async def policy_document(policy_id: str, request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    try:
        pid = UUID(policy_id)
    except ValueError:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    issued = db.scalar(
        select(PolicyIssuedPolicy)
        .options(selectinload(PolicyIssuedPolicy.booking))
        .where(PolicyIssuedPolicy.id == pid)
    )
    if not issued:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    booking = issued.booking
    if booking is None:
        from app.policy.flow import get_booking

        booking = get_booking(db, issued.booking_request_id)
    if booking and booking.user_id != user.id and not can_view_all_claims(user.role):
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    path = Path(issued.document_path)
    if not path.is_file():
        return JSONResponse({"detail": "Document missing"}, status_code=404)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"Policy_{issued.policy_reference}.pdf",
        content_disposition_type="attachment",
    )
