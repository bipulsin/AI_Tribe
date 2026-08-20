"""Policy document generation for the booking module."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from app.policy.constants import DEFAULT_WATERMARK
from app.policy.documents import generate_policy_pdf, policy_docs_dir
from app.policy.models import PolicyBookingRequest, PolicyPayment


def generate_policy_document(
    booking: PolicyBookingRequest,
    *,
    policy_reference: str,
    issue_on: date,
    expiry_on: date,
    watermark: str | None = None,
    payment: PolicyPayment | None = None,
    output_dir: Path | None = None,
) -> Path:
    """Generate the illustrative policy PDF and return its filesystem path."""
    selected = next((q for q in (booking.quotes or []) if q.selected), None)
    customer = booking.customer
    vehicle = booking.vehicle
    if not selected or not customer or not vehicle:
        raise ValueError("A selected quote, vehicle, and customer are required before issuance.")
    folder = output_dir or policy_docs_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"policy_{policy_reference}.pdf"
    generate_policy_pdf(
        output_path=path,
        policy_reference=policy_reference,
        customer_name=customer.name or "-",
        phone=customer.phone or "-",
        id_masked=customer.id_masked or "****",
        registration_number=vehicle.registration_number,
        make=vehicle.make or "-",
        model=vehicle.model or "-",
        year=str(vehicle.year or "-"),
        insurer_name=selected.insurer_name,
        package_type=selected.package_type,
        premium=float(selected.premium),
        issue_on=issue_on,
        expiry_on=expiry_on,
        watermark=watermark or DEFAULT_WATERMARK,
        id_type=customer.id_type,
        dob=customer.dob,
        gender=customer.gender,
        address=customer.address,
        pincode=customer.pincode,
        fuel_type=vehicle.fuel_type,
        color=vehicle.color,
        owner_name=vehicle.owner_name,
        coverage_summary=selected.coverage_summary,
        generated_at=datetime.now(timezone.utc),
    )
    return path
