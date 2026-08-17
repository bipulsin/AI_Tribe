"""Guided finite-state conversation engine for policy booking."""

from __future__ import annotations

import logging
import re
import secrets
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.policy.constants import (
    DEFAULT_WATERMARK,
    HEADER_DISCLAIMER,
    LABEL_DEMO_POLICY,
    LABEL_DEMO_QUOTE,
    LABEL_KYC_SIMULATED,
    SOURCE_DEMO_ISSUANCE,
    STATUS_ISSUED_DEMO,
    STATUS_KYC_PENDING,
    STATUS_KYC_SIMULATED_VALID,
    STATUS_QUOTE_SELECTED,
    STATUS_QUOTED,
    STATUS_STARTED,
    STATUS_VEHICLE_VERIFIED,
    STEPS,
    WELCOME_TEXT,
)
from app.policy.documents import generate_policy_pdf, policy_docs_dir
from app.policy.extraction import (
    enrich_with_nlu,
    extract_policy_fields,
    is_valid_aadhaar,
    is_valid_pan,
    is_valid_phone,
    is_valid_pincode,
    is_valid_registration,
    mask_id_number,
    normalize_phone,
    normalize_registration,
    parse_dob,
)
from app.policy.kyc import MockInsurerTaggedProvider
from app.policy.models import (
    PolicyBookingRequest,
    PolicyConversationMessage,
    PolicyCustomer,
    PolicyIssuedPolicy,
    PolicyKycEvent,
    PolicyQuoteOption,
    PolicyVehicle,
)
from app.policy.quotes import generate_quotes
from app.policy.settings_store import decrypt_secret, encrypt_secret, load_settings, resolved_kyc_mode
from app.policy.vehicle import lookup_vehicle

logger = logging.getLogger("ai_tribe.policy.flow")

STEP_PROMPTS = {
    "collect_registration_number": "Please share the vehicle registration number (for example MH02AB1234).",
    "confirm_vehicle": "Do these vehicle details look correct?",
    "collect_customer_name": "What is the customer's full name?",
    "collect_phone": "What is the 10-digit mobile number?",
    "collect_id_type": "Which ID will we use for simulated KYC — PAN or Aadhaar?",
    "collect_id_number": "Please enter the ID number. It will be stored and shown masked (last four characters only).",
    "collect_dob": "What is the date of birth (YYYY-MM-DD or DD/MM/YYYY)?",
    "collect_gender": "Gender? Male, Female, or Other.",
    "collect_address": "Please share a short correspondence address.",
    "collect_pincode": "What is the 6-digit pincode?",
    "collect_previous_policy": "Is there a previous motor policy on this vehicle? Yes or No.",
    "select_quote": "Select one of the three demo quotations above to continue.",
}


def _eager():
    return [
        selectinload(PolicyBookingRequest.customer),
        selectinload(PolicyBookingRequest.vehicle),
        selectinload(PolicyBookingRequest.messages),
        selectinload(PolicyBookingRequest.kyc_events),
        selectinload(PolicyBookingRequest.quotes),
        selectinload(PolicyBookingRequest.issued_policy),
        selectinload(PolicyBookingRequest.agent),
    ]


def get_booking_by_session(db: Session, session_id: str, user_id: int) -> PolicyBookingRequest | None:
    return db.scalar(
        select(PolicyBookingRequest)
        .options(*_eager())
        .where(
            PolicyBookingRequest.session_id == session_id,
            PolicyBookingRequest.user_id == user_id,
        )
    )


def get_booking(db: Session, booking_id: uuid.UUID, user_id: int | None = None) -> PolicyBookingRequest | None:
    stmt = select(PolicyBookingRequest).options(*_eager()).where(PolicyBookingRequest.id == booking_id)
    if user_id is not None:
        stmt = stmt.where(PolicyBookingRequest.user_id == user_id)
    return db.scalar(stmt)


def _next_reference(db: Session) -> str:
    year = date.today().year
    prefix = f"POL-{year}-"
    last = db.scalar(
        select(func.max(PolicyBookingRequest.booking_reference)).where(
            PolicyBookingRequest.booking_reference.like(f"{prefix}%")
        )
    )
    seq = 1
    if last:
        try:
            seq = int(last.split("-")[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:06d}"


def _ensure_customer(booking: PolicyBookingRequest) -> PolicyCustomer:
    if booking.customer is None:
        booking.customer = PolicyCustomer(booking_request_id=booking.id)
    return booking.customer


def _add_message(
    db: Session,
    booking: PolicyBookingRequest,
    *,
    sender: str,
    text: str,
    message_type: str = "text",
    payload: dict | None = None,
) -> PolicyConversationMessage:
    msg = PolicyConversationMessage(
        booking_request_id=booking.id,
        sender=sender,
        message_type=message_type,
        content_text=text,
        payload=payload,
    )
    db.add(msg)
    db.flush()
    return msg


def _assistant(db: Session, booking: PolicyBookingRequest, text: str, payload: dict | None = None, message_type: str = "text"):
    return _add_message(db, booking, sender="assistant", text=text, payload=payload, message_type=message_type)


def _system(db: Session, booking: PolicyBookingRequest, text: str):
    return _add_message(db, booking, sender="system", text=text, message_type="text")


def start_booking(db: Session, user_id: int) -> PolicyBookingRequest:
    session_id = secrets.token_urlsafe(24)
    booking = PolicyBookingRequest(
        booking_reference=_next_reference(db),
        session_id=session_id,
        user_id=user_id,
        status=STATUS_STARTED,
        current_step="collect_registration_number",
    )
    db.add(booking)
    db.flush()
    _system(db, booking, HEADER_DISCLAIMER)
    _assistant(db, booking, WELCOME_TEXT)
    db.commit()
    db.refresh(booking)
    return get_booking_by_session(db, booking.session_id, user_id) or booking


def serialize_message(msg: PolicyConversationMessage) -> dict[str, Any]:
    created = msg.created_at
    stamp = created.strftime("%H:%M") if created else ""
    return {
        "id": str(msg.id),
        "sender": msg.sender,
        "message_type": msg.message_type,
        "text": msg.content_text,
        "payload": msg.payload or {},
        "timestamp": stamp,
    }


def booking_summary(booking: PolicyBookingRequest) -> dict[str, Any]:
    customer = booking.customer
    vehicle = booking.vehicle
    selected = next((q for q in (booking.quotes or []) if q.selected), None)
    kyc = booking.kyc_events[-1] if booking.kyc_events else None
    issued = booking.issued_policy
    return {
        "booking_reference": booking.booking_reference,
        "status": booking.status,
        "current_step": booking.current_step,
        "registration_number": vehicle.registration_number if vehicle else None,
        "vehicle_label": (
            f"{vehicle.make} {vehicle.model} {vehicle.year or ''}".strip() if vehicle else None
        ),
        "vehicle_source": vehicle.source if vehicle else None,
        "vehicle_source_label": (
            "Live Vahan Lookup" if vehicle and vehicle.source == "live_api" else (
                "Demo Data — Fallback" if vehicle else None
            )
        ),
        "customer_name": customer.name if customer else None,
        "phone": customer.phone if customer else None,
        "id_type": customer.id_type if customer else None,
        "id_masked": customer.id_masked if customer else None,
        "kyc_status": kyc.validation_result if kyc else "pending",
        "kyc_label": LABEL_KYC_SIMULATED if kyc else None,
        "selected_quote": (
            f"{selected.insurer_name} · {selected.package_type} · ₹{selected.premium:,.0f}"
            if selected
            else None
        ),
        "policy_status": "issued_demo" if issued else booking.status,
        "policy_reference": issued.policy_reference if issued else None,
        "disclaimer": HEADER_DISCLAIMER,
    }


def serialize_booking(booking: PolicyBookingRequest) -> dict[str, Any]:
    return {
        "session_id": booking.session_id,
        "booking_id": str(booking.id),
        "booking_reference": booking.booking_reference,
        "current_step": booking.current_step,
        "status": booking.status,
        "messages": [serialize_message(m) for m in booking.messages],
        "summary": booking_summary(booking),
    }


def _apply_extracted(booking: PolicyBookingRequest, fields: dict[str, str]) -> list[str]:
    applied: list[str] = []
    customer = _ensure_customer(booking)
    if fields.get("registration_number") and not (booking.vehicle and booking.vehicle.registration_number):
        applied.append("registration_number")
        booking._pending_registration = fields["registration_number"]  # type: ignore[attr-defined]
    if fields.get("customer_name") and not customer.name:
        customer.name = fields["customer_name"][:128]
        applied.append("name")
    if fields.get("phone") and not customer.phone:
        customer.phone = normalize_phone(fields["phone"])
        applied.append("phone")
    if fields.get("id_type") and not customer.id_type:
        kind = fields["id_type"]
        customer.id_type = "PAN" if kind.upper() == "PAN" else "Aadhaar"
        applied.append("id_type")
    if fields.get("id_number") and not customer.id_encrypted:
        customer.id_encrypted = encrypt_secret(fields["id_number"])
        customer.id_masked = mask_id_number(fields["id_number"])
        applied.append("id_number")
    if fields.get("dob") and not customer.dob:
        customer.dob = fields["dob"]
        applied.append("dob")
    if fields.get("gender") and not customer.gender:
        customer.gender = fields["gender"]
        applied.append("gender")
    if fields.get("address") and not customer.address:
        customer.address = fields["address"][:255]
        applied.append("address")
    if fields.get("pincode") and not customer.pincode:
        customer.pincode = fields["pincode"]
        applied.append("pincode")
    if fields.get("previous_policy") and booking.previous_policy_declared is None:
        booking.previous_policy_declared = fields["previous_policy"] == "yes"
        applied.append("previous_policy")
    return applied


def _missing_step(booking: PolicyBookingRequest) -> str:
    customer = booking.customer
    vehicle = booking.vehicle
    if not vehicle or not vehicle.registration_number:
        pending = getattr(booking, "_pending_registration", None)
        if not pending:
            return "collect_registration_number"
        return "vehicle_lookup"
    if not vehicle.confirmed:
        return "confirm_vehicle"
    if not customer or not customer.name:
        return "collect_customer_name"
    if not customer.phone:
        return "collect_phone"
    if not customer.id_type:
        return "collect_id_type"
    if not customer.id_masked:
        return "collect_id_number"
    if not customer.dob:
        return "collect_dob"
    if not customer.gender:
        return "collect_gender"
    if not customer.address:
        return "collect_address"
    if not customer.pincode:
        return "collect_pincode"
    if booking.previous_policy_declared is None:
        return "collect_previous_policy"
    if not booking.kyc_events or booking.kyc_events[-1].validation_result != "valid":
        return "kyc_simulation"
    if not booking.quotes:
        return "generate_quotes"
    if not any(q.selected for q in booking.quotes):
        return "select_quote"
    if not booking.issued_policy:
        return "issue_policy"
    return "completed"


def _prompt_for(db: Session, booking: PolicyBookingRequest, step: str) -> None:
    if step == "collect_id_type":
        _assistant(
            db,
            booking,
            STEP_PROMPTS[step],
            message_type="chip",
            payload={
                "kind": "chips",
                "options": [
                    {"label": "PAN", "value": "PAN"},
                    {"label": "Aadhaar", "value": "Aadhaar"},
                ],
            },
        )
        return
    if step == "collect_gender":
        _assistant(
            db,
            booking,
            STEP_PROMPTS[step],
            message_type="chip",
            payload={
                "kind": "chips",
                "options": [
                    {"label": "Male", "value": "Male"},
                    {"label": "Female", "value": "Female"},
                    {"label": "Other", "value": "Other"},
                ],
            },
        )
        return
    if step == "collect_previous_policy":
        _assistant(
            db,
            booking,
            STEP_PROMPTS[step],
            message_type="chip",
            payload={
                "kind": "chips",
                "options": [
                    {"label": "Yes", "value": "yes"},
                    {"label": "No", "value": "no"},
                ],
            },
        )
        return
    if step == "confirm_vehicle" and booking.vehicle:
        v = booking.vehicle
        label = "Live Vahan Lookup" if v.source == "live_api" else "Demo Data — Fallback"
        _assistant(
            db,
            booking,
            "Please confirm these vehicle details before we continue.",
            message_type="card",
            payload={
                "kind": "vehicle_card",
                "source_label": label,
                "registration_number": v.registration_number,
                "make": v.make,
                "model": v.model,
                "year": v.year,
                "color": v.color,
                "fuel_type": v.fuel_type,
                "owner_name": v.owner_name,
                "options": [
                    {"label": "Yes, details are correct", "value": "confirm_vehicle"},
                    {"label": "No, re-enter number", "value": "reject_vehicle"},
                ],
            },
        )
        return
    text = STEP_PROMPTS.get(step)
    if text:
        _assistant(db, booking, text)


def _run_vehicle_lookup(db: Session, booking: PolicyBookingRequest, registration: str, user_id: int) -> None:
    stored = load_settings(db, user_id)
    result = lookup_vehicle(registration, force_fallback=bool(stored.get("force_demo_fallback")))
    vehicle = booking.vehicle
    if vehicle is None:
        vehicle = PolicyVehicle(booking_request_id=booking.id, registration_number=result.registration_number)
        booking.vehicle = vehicle
        db.add(vehicle)
    vehicle.registration_number = result.registration_number
    vehicle.make = result.make
    vehicle.model = result.model
    vehicle.year = result.year
    vehicle.color = result.color
    vehicle.fuel_type = result.fuel_type
    vehicle.owner_name = result.owner_name
    vehicle.source = result.source
    vehicle.raw_payload = result.raw_payload
    vehicle.confirmed = False
    booking.status = STATUS_VEHICLE_VERIFIED
    booking.current_step = "confirm_vehicle"
    _system(db, booking, f"Vehicle lookup source: {result.source_label}")
    _prompt_for(db, booking, "confirm_vehicle")


def _run_kyc(db: Session, booking: PolicyBookingRequest, id_number: str, user_id: int) -> None:
    stored = load_settings(db, user_id)
    mode, _warning = resolved_kyc_mode(stored)
    customer = _ensure_customer(booking)
    attempt = len(booking.kyc_events) + 1
    result = MockInsurerTaggedProvider().validate(
        id_type=customer.id_type or "PAN",
        id_number=id_number,
        attempt_number=attempt,
    )
    customer.id_masked = result.id_masked
    customer.id_type = result.id_type
    if result.valid:
        customer.id_encrypted = None
    else:
        customer.id_encrypted = None
        customer.id_masked = None
    event = PolicyKycEvent(
        booking_request_id=booking.id,
        id_type=result.id_type,
        id_number_masked=result.id_masked,
        validation_mode=mode,
        validation_result="valid" if result.valid else "invalid",
        attempt_number=attempt,
        demo_mode=True,
        reason=result.reason,
    )
    db.add(event)
    db.flush()
    booking.kyc_events.append(event)
    booking.kyc_mode_used = mode
    booking.status = STATUS_KYC_SIMULATED_VALID if result.valid else STATUS_KYC_PENDING
    _assistant(
        db,
        booking,
        (
            f"KYC result: **{'Valid' if result.valid else 'Invalid'}**.\n"
            f"{LABEL_KYC_SIMULATED}\n"
            f"ID type: {result.id_type} · Masked ID: {result.id_masked}"
            + (f"\nReason: {result.reason}" if result.reason else "")
        ),
        message_type="card",
        payload={
            "kind": "kyc_card",
            "label": LABEL_KYC_SIMULATED,
            "valid": result.valid,
            "id_type": result.id_type,
            "id_masked": result.id_masked,
            "reason": result.reason,
        },
    )
    if result.valid:
        booking.current_step = "generate_quotes"
        _run_quotes(db, booking, user_id)
    else:
        booking.current_step = "collect_id_number"
        _assistant(db, booking, "Please re-enter the ID number. Simulated KYC will accept the retry in this session.")


def _run_quotes(db: Session, booking: PolicyBookingRequest, user_id: int) -> None:
    stored = load_settings(db, user_id)
    vehicle = booking.vehicle
    customer = booking.customer
    drafts = generate_quotes(
        year=vehicle.year if vehicle else None,
        make=vehicle.make if vehicle else None,
        pincode=customer.pincode if customer else None,
        previous_policy=booking.previous_policy_declared,
        floors=(
            float(stored.get("premium_floor_a") or 8000),
            float(stored.get("premium_floor_b") or 12000),
            float(stored.get("premium_floor_c") or 18000),
        ),
        randomized=bool(stored.get("quotes_randomized", True)),
        seed=str(booking.id),
    )
    for existing in list(booking.quotes or []):
        db.delete(existing)
    booking.quotes = []
    db.flush()
    cards = []
    for draft in drafts:
        row = PolicyQuoteOption(
            booking_request_id=booking.id,
            insurer_code=draft.insurer_code,
            insurer_name=draft.insurer_name,
            premium=draft.premium,
            package_type=draft.package_type,
            coverage_summary=draft.coverage_summary,
            validity_note=draft.validity_note,
            source_mode=draft.source_mode,
            selected=False,
        )
        db.add(row)
        db.flush()
        booking.quotes.append(row)
        cards.append(
            {
                "id": str(row.id),
                "insurer_code": draft.insurer_code,
                "insurer_name": draft.insurer_name,
                "package_type": draft.package_type,
                "premium": draft.premium,
                "coverage_summary": draft.coverage_summary,
                "validity_note": draft.validity_note,
                "label": LABEL_DEMO_QUOTE,
            }
        )
    booking.status = STATUS_QUOTED
    booking.current_step = "select_quote"
    _assistant(
        db,
        booking,
        "Here are three **demo quotations**. Premiums are illustrative only — not insurer API prices.",
        message_type="quote",
        payload={"kind": "quote_cards", "label": LABEL_DEMO_QUOTE, "quotes": cards},
    )


def _issue_policy(db: Session, booking: PolicyBookingRequest, user_id: int) -> None:
    selected = next((q for q in booking.quotes if q.selected), None)
    if not selected or not booking.vehicle or not booking.customer:
        _assistant(db, booking, "A selected quote, vehicle, and customer are required before issuance.")
        return
    stored = load_settings(db, user_id)
    watermark = stored.get("watermark_text") or DEFAULT_WATERMARK
    today = date.today()
    try:
        expiry = date(today.year + 1, today.month, today.day)
    except ValueError:
        expiry = today + timedelta(days=365)
    policy_ref = f"DMO-POL-{today.strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
    filename = f"{policy_ref}.pdf"
    path = policy_docs_dir() / filename
    generate_policy_pdf(
        output_path=path,
        policy_reference=policy_ref,
        customer_name=booking.customer.name or "-",
        phone=booking.customer.phone or "-",
        id_masked=booking.customer.id_masked or "****",
        registration_number=booking.vehicle.registration_number,
        make=booking.vehicle.make or "-",
        model=booking.vehicle.model or "-",
        year=str(booking.vehicle.year or "-"),
        insurer_name=selected.insurer_name,
        package_type=selected.package_type,
        premium=float(selected.premium),
        issue_on=today,
        expiry_on=expiry,
        watermark=watermark,
    )
    issued = PolicyIssuedPolicy(
        booking_request_id=booking.id,
        policy_reference=policy_ref,
        document_path=str(path),
        issue_date=today,
        expiry_date=expiry,
        source_mode=SOURCE_DEMO_ISSUANCE,
        insurer_name=selected.insurer_name,
        package_type=selected.package_type,
        premium=float(selected.premium),
    )
    db.add(issued)
    booking.issued_policy = issued
    booking.status = STATUS_ISSUED_DEMO
    booking.current_step = "completed"
    _assistant(
        db,
        booking,
        (
            f"Demo policy created.\n"
            f"**{LABEL_DEMO_POLICY}**\n"
            f"Reference: {policy_ref}\n"
            f"{selected.insurer_name} · {selected.package_type} · ₹{selected.premium:,.0f}"
        ),
        message_type="document",
        payload={
            "kind": "document",
            "label": LABEL_DEMO_POLICY,
            "policy_id": str(issued.id),
            "policy_reference": policy_ref,
            "insurer_name": selected.insurer_name,
            "premium": float(selected.premium),
            "download_url": f"/policy/document/{issued.id}",
        },
    )


def _handle_current_input(db: Session, booking: PolicyBookingRequest, text: str, user_id: int) -> bool:
    """Return True if the utterance was consumed by the current step."""
    step = booking.current_step
    raw = (text or "").strip()
    lowered = raw.lower()
    customer = _ensure_customer(booking)

    if step == "collect_registration_number":
        if is_valid_registration(raw):
            booking._pending_registration = normalize_registration(raw)  # type: ignore[attr-defined]
            return True
        extracted = extract_policy_fields(raw)
        if extracted.get("registration_number"):
            booking._pending_registration = extracted["registration_number"]  # type: ignore[attr-defined]
            return True
        return False

    if step == "confirm_vehicle":
        if lowered in {"confirm_vehicle", "yes", "y", "correct", "ok", "yes, details are correct"}:
            if booking.vehicle:
                booking.vehicle.confirmed = True
            return True
        if lowered in {"reject_vehicle", "no", "n", "re-enter", "no, re-enter number"}:
            if booking.vehicle:
                db.delete(booking.vehicle)
                booking.vehicle = None
            booking.current_step = "collect_registration_number"
            booking.status = STATUS_STARTED
            _assistant(db, booking, "No problem. " + STEP_PROMPTS["collect_registration_number"])
            return True
        return False

    if step == "collect_customer_name":
        if len(raw) >= 2 and not is_valid_registration(raw) and not is_valid_phone(raw):
            customer.name = raw[:128]
            return True
        return False

    if step == "collect_phone":
        if is_valid_phone(raw):
            customer.phone = normalize_phone(raw)
            return True
        return False

    if step == "collect_id_type":
        if lowered in {"pan", "aadhaar", "aadhar"}:
            customer.id_type = "PAN" if lowered == "pan" else "Aadhaar"
            return True
        return False

    if step == "collect_id_number":
        kind = (customer.id_type or "").upper()
        ok = is_valid_pan(raw) if kind == "PAN" else is_valid_aadhaar(raw)
        if ok:
            customer.id_encrypted = encrypt_secret(raw)
            customer.id_masked = mask_id_number(raw)
            return True
        return False

    if step == "collect_dob":
        parsed = parse_dob(raw)
        if parsed:
            customer.dob = parsed
            return True
        return False

    if step == "collect_gender":
        if lowered in {"male", "female", "other"}:
            customer.gender = lowered.title()
            return True
        return False

    if step == "collect_address":
        if len(raw) >= 6:
            customer.address = raw[:255]
            return True
        return False

    if step == "collect_pincode":
        if is_valid_pincode(raw):
            customer.pincode = raw.strip()
            return True
        return False

    if step == "collect_previous_policy":
        if lowered in {"yes", "y", "no", "n"}:
            booking.previous_policy_declared = lowered.startswith("y")
            return True
        return False

    if step == "select_quote":
        code = None
        match = re.search(r"(?:select_quote:|insurer\s+)?([abc])\b", lowered)
        if match:
            code = match.group(1).upper()
        for quote in booking.quotes:
            if raw == str(quote.id) or (code and quote.insurer_code == code):
                for other in booking.quotes:
                    other.selected = other.id == quote.id
                booking.status = STATUS_QUOTE_SELECTED
                return True
            if lowered in {quote.insurer_name.lower(), quote.package_type.lower()}:
                for other in booking.quotes:
                    other.selected = other.id == quote.id
                booking.status = STATUS_QUOTE_SELECTED
                return True
        return False

    return False


def _advance_autos(db: Session, booking: PolicyBookingRequest, user_id: int) -> None:
    guard = 0
    while guard < 8:
        guard += 1
        nxt = _missing_step(booking)
        booking.current_step = nxt
        if nxt == "vehicle_lookup":
            reg = getattr(booking, "_pending_registration", None)
            if not reg and booking.vehicle:
                reg = booking.vehicle.registration_number
            if not reg:
                booking.current_step = "collect_registration_number"
                return
            _run_vehicle_lookup(db, booking, reg, user_id)
            continue
        if nxt == "kyc_simulation":
            ident = None
            if booking.customer and booking.customer.id_encrypted:
                try:
                    ident = decrypt_secret(booking.customer.id_encrypted)
                except Exception:
                    ident = None
            if not ident:
                booking.current_step = "collect_id_number"
                _prompt_for(db, booking, "collect_id_number")
                return
            _run_kyc(db, booking, ident, user_id)
            continue
        if nxt == "generate_quotes":
            _run_quotes(db, booking, user_id)
            continue
        if nxt == "issue_policy":
            _issue_policy(db, booking, user_id)
            continue
        if nxt == "completed":
            return
        return


def handle_user_message(db: Session, booking: PolicyBookingRequest, text: str, user_id: int) -> PolicyBookingRequest:
    raw = (text or "").strip()
    if not raw:
        _assistant(db, booking, "I did not catch that. " + STEP_PROMPTS.get(booking.current_step, "Please continue."))
        db.commit()
        return booking

    if booking.current_step == "completed":
        _add_message(db, booking, sender="user", text=raw)
        _assistant(
            db,
            booking,
            "This demo booking is complete. Start a new booking from the header if you want another journey.",
        )
        db.commit()
        return get_booking_by_session(db, booking.session_id, user_id) or booking

    _add_message(db, booking, sender="user", text=raw)

    fields = enrich_with_nlu(raw, extract_policy_fields(raw))
    applied = _apply_extracted(booking, fields)
    consumed = _handle_current_input(db, booking, raw, user_id)

    if not consumed and not applied:
        _assistant(
            db,
            booking,
            (
                f"I noted that, but we are currently on **{booking.current_step.replace('_', ' ')}**. "
                "Let me re-ask for the missing information."
            ),
        )
        _prompt_for(db, booking, booking.current_step)
        db.commit()
        return get_booking_by_session(db, booking.session_id, user_id) or booking

    _advance_autos(db, booking, user_id)
    nxt = _missing_step(booking)
    booking.current_step = nxt
    if nxt not in {"vehicle_lookup", "kyc_simulation", "generate_quotes", "issue_policy", "completed"}:
        # Avoid duplicate prompts if auto step already asked.
        last = booking.messages[-1] if booking.messages else None
        already = bool(last and last.sender == "assistant" and last.payload)
        if nxt == "confirm_vehicle" and already:
            pass
        elif nxt == "select_quote" and already:
            pass
        else:
            _prompt_for(db, booking, nxt)
    db.commit()
    return get_booking_by_session(db, booking.session_id, user_id) or booking
