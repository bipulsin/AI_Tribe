"""CRM listing helpers for policy bookings."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.roles import can_view_all_claims
from app.policy.models import PolicyBookingRequest, PolicyCustomer, PolicyVehicle


def list_bookings(
    db: Session,
    *,
    user_id: int,
    role: str | None,
    status: str | None = None,
    registration: str | None = None,
    phone: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[PolicyBookingRequest]:
    stmt = (
        select(PolicyBookingRequest)
        .options(
            selectinload(PolicyBookingRequest.customer),
            selectinload(PolicyBookingRequest.vehicle),
            selectinload(PolicyBookingRequest.quotes),
            selectinload(PolicyBookingRequest.issued_policy),
            selectinload(PolicyBookingRequest.agent),
        )
        .order_by(PolicyBookingRequest.created_at.desc())
    )
    if not can_view_all_claims(role):
        stmt = stmt.where(PolicyBookingRequest.user_id == user_id)
    if status:
        stmt = stmt.where(PolicyBookingRequest.status == status)
    if date_from:
        stmt = stmt.where(PolicyBookingRequest.created_at >= date_from)
    if date_to:
        stmt = stmt.where(PolicyBookingRequest.created_at <= date_to)
    if registration:
        compact = registration.strip().upper()
        stmt = stmt.join(PolicyVehicle).where(PolicyVehicle.registration_number.ilike(f"%{compact}%"))
    if phone:
        digits = "".join(ch for ch in phone if ch.isdigit())
        stmt = stmt.join(PolicyCustomer).where(PolicyCustomer.phone.ilike(f"%{digits}%"))
    return list(db.scalars(stmt).unique().all())
