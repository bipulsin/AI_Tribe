"""Policy module HTML pages: chat shell, CRM, settings, summary fragment."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import session_user
from app.core.database import get_db
from app.core.templates import templates
from app.models import User
from app.policy.constants import HEADER_DISCLAIMER, SESSION_COOKIE, SESSION_MAX_AGE, STATUSES
from app.policy.crm import list_bookings
from app.policy.flow import booking_summary, get_booking, get_booking_by_session, serialize_booking, start_booking
from app.policy.settings_store import public_settings_view

router = APIRouter(tags=["policy"])


def _user(request: Request, db: Session) -> User:
    user = session_user(request, db)
    assert user is not None
    return user


def attach_session_cookie(response, session_id: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


@router.get("/policy", response_class=HTMLResponse)
async def policy_chat_page(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    session_id = request.cookies.get(SESSION_COOKIE)
    booking = get_booking_by_session(db, session_id, user.id) if session_id else None
    if booking is None:
        booking = start_booking(db, user.id)
    payload = serialize_booking(booking)
    response = templates.TemplateResponse(
        "policy/chat.html",
        {
            "request": request,
            "disclaimer": HEADER_DISCLAIMER,
            "bootstrap": payload,
            "summary": payload["summary"],
        },
    )
    attach_session_cookie(response, booking.session_id)
    return response


@router.get("/policy/summary", response_class=HTMLResponse)
async def policy_summary(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    session_id = request.cookies.get(SESSION_COOKIE)
    booking = get_booking_by_session(db, session_id, user.id) if session_id else None
    return templates.TemplateResponse(
        "policy/partials/summary.html",
        {
            "request": request,
            "summary": booking_summary(booking) if booking else {},
        },
    )


@router.get("/policy/crm", response_class=HTMLResponse)
async def policy_crm_list(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    status = (request.query_params.get("status") or "").strip() or None
    registration = (request.query_params.get("registration") or "").strip() or None
    phone = (request.query_params.get("phone") or "").strip() or None
    date_from_raw = (request.query_params.get("date_from") or "").strip()
    date_to_raw = (request.query_params.get("date_to") or "").strip()
    date_from = datetime.fromisoformat(date_from_raw) if date_from_raw else None
    date_to = datetime.fromisoformat(date_to_raw + "T23:59:59") if date_to_raw else None
    rows = list_bookings(
        db,
        user_id=user.id,
        role=user.role,
        status=status,
        registration=registration,
        phone=phone,
        date_from=date_from,
        date_to=date_to,
    )
    context = {
        "request": request,
        "rows": rows,
        "statuses": STATUSES,
        "filters": {
            "status": status or "",
            "registration": registration or "",
            "phone": phone or "",
            "date_from": date_from_raw,
            "date_to": date_to_raw,
        },
    }
    if request.headers.get("hx-request"):
        return templates.TemplateResponse("policy/partials/crm_table.html", context)
    return templates.TemplateResponse("policy/crm_list.html", context)


@router.get("/policy/crm/{booking_id}", response_class=HTMLResponse)
async def policy_crm_detail(booking_id: str, request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    from uuid import UUID

    try:
        bid = UUID(booking_id)
    except ValueError:
        return RedirectResponse("/policy/crm", status_code=303)
    from app.core.roles import can_view_all_claims

    booking = get_booking(db, bid, None if can_view_all_claims(user.role) else user.id)
    if not booking:
        return RedirectResponse("/policy/crm", status_code=303)
    return templates.TemplateResponse(
        "policy/crm_detail.html",
        {"request": request, "booking": booking, "summary": booking_summary(booking)},
    )


@router.get("/policy/settings", response_class=HTMLResponse)
async def policy_settings_page(request: Request, db: Session = Depends(get_db)):
    user = _user(request, db)
    return templates.TemplateResponse(
        "policy/settings.html",
        {"request": request, "settings_view": public_settings_view(db, user.id)},
    )
