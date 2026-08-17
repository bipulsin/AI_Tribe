"""Quote generation and selection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import session_user
from app.core.database import get_db
from app.policy.constants import LABEL_DEMO_QUOTE, SESSION_COOKIE
from app.policy.flow import get_booking_by_session, handle_user_message, serialize_booking
from app.policy.quotes import generate_quotes
from app.policy.settings_store import load_settings

router = APIRouter(tags=["policy-quotes"])


class QuoteSelectPayload(BaseModel):
    insurer_code: str = Field(default="A", max_length=8)


@router.post("/policy/quotes/generate")
async def policy_quotes_generate(request: Request, db: Session = Depends(get_db)):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    session_id = request.cookies.get(SESSION_COOKIE)
    booking = get_booking_by_session(db, session_id, user.id) if session_id else None
    stored = load_settings(db, user.id)
    if booking and booking.vehicle:
        drafts = generate_quotes(
            year=booking.vehicle.year,
            make=booking.vehicle.make,
            pincode=booking.customer.pincode if booking.customer else None,
            previous_policy=booking.previous_policy_declared,
            floors=(
                float(stored.get("premium_floor_a") or 8000),
                float(stored.get("premium_floor_b") or 12000),
                float(stored.get("premium_floor_c") or 18000),
            ),
            randomized=bool(stored.get("quotes_randomized", True)),
            seed=str(booking.id),
        )
        return {
            "label": LABEL_DEMO_QUOTE,
            "quotes": [
                {
                    "insurer_code": d.insurer_code,
                    "insurer_name": d.insurer_name,
                    "package_type": d.package_type,
                    "premium": d.premium,
                    "coverage_summary": d.coverage_summary,
                    "label": LABEL_DEMO_QUOTE,
                }
                for d in drafts
            ],
        }
    drafts = generate_quotes(
        year=2021,
        make="Maruti",
        pincode="400001",
        previous_policy=True,
        floors=(8000, 12000, 18000),
        randomized=False,
        seed="preview",
    )
    return {
        "label": LABEL_DEMO_QUOTE,
        "quotes": [
            {
                "insurer_code": d.insurer_code,
                "insurer_name": d.insurer_name,
                "package_type": d.package_type,
                "premium": d.premium,
                "coverage_summary": d.coverage_summary,
                "label": LABEL_DEMO_QUOTE,
            }
            for d in drafts
        ],
    }


@router.post("/policy/quotes/select")
async def policy_quotes_select(
    payload: QuoteSelectPayload, request: Request, db: Session = Depends(get_db)
):
    user = session_user(request, db)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    session_id = request.cookies.get(SESSION_COOKIE)
    booking = get_booking_by_session(db, session_id, user.id) if session_id else None
    if not booking:
        return JSONResponse({"detail": "No active booking"}, status_code=404)
    booking = handle_user_message(db, booking, f"select_quote:{payload.insurer_code}", user.id)
    return serialize_booking(booking)
