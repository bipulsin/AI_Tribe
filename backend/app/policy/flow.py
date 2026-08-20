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
    KYC_MODE_EKO_PAN,
    LABEL_DEMO_FALLBACK,
    LABEL_DEMO_POLICY,
    LABEL_DEMO_QUOTE,
    LABEL_KYC_EKO_PAN,
    LABEL_KYC_SIMULATED,
    LABEL_LIVE_VAHAN,
    LABEL_PAYMENT,
    PAYMENT_METHOD_LABELS,
    PAYMENT_METHODS,
    SOURCE_DEMO_ISSUANCE,
    STATUS_ISSUED_DEMO,
    STATUS_KYC_PENDING,
    STATUS_KYC_SIMULATED_VALID,
    STATUS_PAYMENT_CONFIRMED,
    STATUS_QUOTE_SELECTED,
    STATUS_QUOTED,
    STATUS_STARTED,
    STATUS_VEHICLE_VERIFIED,
    STEPS,
    WELCOME_TEXT,
)
from app.policy.extraction import (
    enrich_with_nlu,
    extract_policy_fields,
    is_valid_aadhaar,
    is_valid_pan,
    is_valid_phone,
    is_valid_pincode,
    is_valid_registration,
    mask_card_last4,
    mask_expiry,
    mask_id_number,
    normalize_phone,
    normalize_registration,
    parse_dob,
)
from app.policy.kyc import EkoKycProvider, MockInsurerTaggedProvider
from app.policy.vehicle import is_blacklist_flag, lookup_vehicle
from app.policy.models import (
    PolicyBookingRequest,
    PolicyConversationMessage,
    PolicyCustomer,
    PolicyIssuedPolicy,
    PolicyKycEvent,
    PolicyPayment,
    PolicyQuoteOption,
    PolicyVehicle,
)
from app.policy.quotes import generate_quotes
from app.policy.settings_store import decrypt_secret, encrypt_secret, load_settings, resolved_kyc_mode
from app.services.policy_document import generate_policy_document

logger = logging.getLogger("ai_tribe.policy.flow")

STEP_PROMPTS = {
    "collect_registration_number": "Please share the vehicle registration number (for example MH02AB1234).",
    "confirm_vehicle": "Do these vehicle details look correct?",
    "confirm_blacklist": "This vehicle appears on a blacklist. Do you want to continue anyway?",
    "collect_customer_name": "What is the customer's full name?",
    "collect_phone": "What is the 10-digit mobile number?",
    "collect_id_type": "Which ID will we use for KYC — PAN or Aadhaar?",
    "collect_id_number": "Please enter the ID number. It will be stored and shown masked (last four characters only).",
    "collect_dob": "What is the date of birth (YYYY-MM-DD or DD/MM/YYYY)?",
    "collect_gender": "Gender? Male, Female, or Other.",
    "collect_address": "Please share a short correspondence address.",
    "collect_pincode": "What is the 6-digit pincode?",
    "collect_previous_policy": "Is there a previous motor policy on this vehicle? Yes or No.",
    "select_quote": "Select one of the three illustrative quotations above to continue.",
    "initiate_payment": "Complete the simulated payment below to issue the policy document.",
    "confirm_kyc_partial": "The PAN is valid but name or DOB did not match exactly. Continue anyway?",
    "policy_issued": "This booking is complete. You can download your policy above.",
}


def _eager():
    return [
        selectinload(PolicyBookingRequest.customer),
        selectinload(PolicyBookingRequest.vehicle),
        selectinload(PolicyBookingRequest.messages),
        selectinload(PolicyBookingRequest.kyc_events),
        selectinload(PolicyBookingRequest.quotes),
        selectinload(PolicyBookingRequest.payments),
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
            LABEL_LIVE_VAHAN if vehicle and vehicle.source == "live_api" else (
                LABEL_DEMO_FALLBACK if vehicle else None
            )
        ),
        "customer_name": customer.name if customer else None,
        "phone": customer.phone if customer else None,
        "id_type": customer.id_type if customer else None,
        "id_masked": customer.id_masked if customer else None,
        "kyc_status": kyc.validation_result if kyc else "pending",
        "kyc_label": (
            (LABEL_KYC_EKO_PAN if kyc.validation_mode == KYC_MODE_EKO_PAN else LABEL_KYC_SIMULATED)
            if kyc
            else None
        ),
        "blacklist_status": vehicle.blacklist_status if vehicle else None,
        "blacklisted": bool(vehicle and is_blacklist_flag(vehicle.blacklist_status)),
        "rc_status": vehicle.rc_status if vehicle else None,
        "insurance_validity": vehicle.insurance_validity if vehicle else None,
        "selected_quote": (
            f"{selected.insurer_name} · {selected.package_type} · ₹{selected.premium:,.0f}"
            if selected
            else None
        ),
        "payment_method": booking.payment_method,
        "payment_method_label": PAYMENT_METHOD_LABELS.get(booking.payment_method or "", booking.payment_method),
        "payment_status": (
            booking.payments[-1].status if booking.payments else None
        ),
        "policy_status": "issued (illustrative)" if issued else booking.status,
        "policy_reference": issued.policy_reference if issued else None,
        "policy_download_url": f"/policy/document/{issued.id}" if issued else None,
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
        if is_blacklist_flag(vehicle.blacklist_status) and not vehicle.blacklist_acknowledged:
            return "confirm_blacklist"
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
    if not booking.kyc_events or booking.kyc_events[-1].validation_result not in {"valid", "partial"}:
        return "kyc_simulation"
    if booking.kyc_events[-1].validation_result == "partial":
        return "confirm_kyc_partial"
    if not booking.quotes:
        return "generate_quotes"
    if not any(q.selected for q in booking.quotes):
        return "select_quote"
    if not _payment_succeeded(booking):
        return "initiate_payment"
    if not booking.issued_policy:
        return "issue_policy"
    return "completed"


def _payment_succeeded(booking: PolicyBookingRequest) -> bool:
    if booking.status in {STATUS_PAYMENT_CONFIRMED, STATUS_ISSUED_DEMO}:
        return True
    for payment in booking.payments or []:
        if str(payment.status or "") in {"success", "simulated"}:
            return True
    return False


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
        label = LABEL_LIVE_VAHAN if v.source == "live_api" else LABEL_DEMO_FALLBACK
        extra_lines = []
        if v.rc_status:
            extra_lines.append(f"RC status: {v.rc_status}")
        if v.fuel_type:
            extra_lines.append(f"Fuel: {v.fuel_type}")
        if v.insurance_validity:
            extra_lines.append(f"Insurance validity: {v.insurance_validity}")
        extra_lines.append(f"Blacklist status: {v.blacklist_status or 'Not reported'}")
        _assistant(
            db,
            booking,
            "Please confirm these vehicle details before we continue.\n" + "\n".join(extra_lines),
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
                "rc_status": v.rc_status,
                "insurance_validity": v.insurance_validity,
                "blacklist_status": v.blacklist_status,
                "blacklisted": is_blacklist_flag(v.blacklist_status),
                "options": [
                    {"label": "Yes, details are correct", "value": "confirm_vehicle"},
                    {"label": "No, re-enter number", "value": "reject_vehicle"},
                ],
            },
        )
        return
    if step == "confirm_blacklist" and booking.vehicle:
        v = booking.vehicle
        _assistant(
            db,
            booking,
            (
                f"**Blacklist warning:** status is `{v.blacklist_status}`.\n"
                "Do you want to continue with this booking?"
            ),
            message_type="card",
            payload={
                "kind": "blacklist_warning",
                "blacklist_status": v.blacklist_status,
                "registration_number": v.registration_number,
                "options": [
                    {"label": "Continue anyway", "value": "continue_blacklist"},
                    {"label": "Start over", "value": "reset_booking"},
                ],
            },
        )
        return
    if step == "confirm_kyc_partial":
        _assistant(
            db,
            booking,
            STEP_PROMPTS["confirm_kyc_partial"],
            message_type="chip",
            payload={
                "kind": "chips",
                "options": [
                    {"label": "Continue", "value": "continue_kyc"},
                    {"label": "Re-enter PAN", "value": "retry_kyc"},
                ],
            },
        )
        return
    if step == "initiate_payment":
        selected = next((q for q in (booking.quotes or []) if q.selected), None)
        if not selected:
            _assistant(db, booking, "Select a quotation before continuing to payment.")
            return
        _assistant(
            db,
            booking,
            (
                f"Pay the illustrative premium for **{selected.insurer_name}** "
                f"({selected.package_type}) — ₹{float(selected.premium):,.0f}."
            ),
            message_type="card",
            payload={
                "kind": "payment_card",
                "label": LABEL_PAYMENT,
                "insurer_name": selected.insurer_name,
                "package_type": selected.package_type,
                "premium": float(selected.premium),
                "session_id": booking.session_id,
            },
        )
        return
    text = STEP_PROMPTS.get(step)
    if text:
        _assistant(db, booking, text)


def _run_vehicle_lookup(db: Session, booking: PolicyBookingRequest, registration: str, user_id: int) -> None:
    stored = load_settings(db, user_id)
    try:
        result = lookup_vehicle(
            registration,
            force_fallback=bool(stored.get("force_demo_fallback")),
            session_id=booking.session_id,
        )
    except Exception:
        logger.exception("vehicle lookup crashed — using mimic data")
        from app.policy.vehicle import DemoFallbackProvider

        result = DemoFallbackProvider().lookup(registration)
    if result.not_found or result.error == "invalid_format":
        _assistant(
            db,
            booking,
            result.user_notice or "That registration number could not be verified. Please resubmit.",
        )
        booking.current_step = "collect_registration_number"
        booking.status = STATUS_STARTED
        return
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
    vehicle.source = result.source or "demo_fallback"
    vehicle.raw_payload = result.raw_payload
    vehicle.client_ref_id = result.client_ref_id
    vehicle.rc_status = result.rc_status
    vehicle.insurance_validity = result.insurance_validity
    vehicle.blacklist_status = result.blacklist_status
    vehicle.blacklist_acknowledged = False
    vehicle.confirmed = False
    booking.status = STATUS_VEHICLE_VERIFIED
    if result.user_notice:
        _system(db, booking, result.user_notice)
    _system(db, booking, f"Vehicle lookup source: {result.source_label}")
    if result.blacklisted or is_blacklist_flag(vehicle.blacklist_status):
        booking.current_step = "confirm_blacklist"
        _prompt_for(db, booking, "confirm_blacklist")
        return
    booking.current_step = "confirm_vehicle"
    _prompt_for(db, booking, "confirm_vehicle")


def _run_kyc(db: Session, booking: PolicyBookingRequest, id_number: str, user_id: int) -> None:
    stored = load_settings(db, user_id)
    mode, _warning = resolved_kyc_mode(stored)
    customer = _ensure_customer(booking)
    attempt = len(booking.kyc_events) + 1
    id_type = customer.id_type or "PAN"
    result = None
    if mode == KYC_MODE_EKO_PAN and id_type.upper() == "PAN":
        eko = EkoKycProvider()
        if eko.available:
            try:
                result = eko.validate_pan(
                    pan_number=id_number,
                    name=customer.name or "",
                    dob=customer.dob or "",
                    session_id=booking.session_id,
                    attempt_number=attempt,
                )
            except Exception:
                logger.exception("EKO PAN lookup crashed — using simulated verification")
                result = MockInsurerTaggedProvider().validate(
                    id_type=id_type,
                    id_number=id_number,
                    attempt_number=max(2, attempt),
                )
                result.fallback_to_mock = True
                result.valid = True
                result.match_kind = "full"
                result.user_notice = "Live PAN verification was unavailable. Using simulated verification."
            if result.fallback_to_mock:
                _system(
                    db,
                    booking,
                    result.user_notice
                    or "Live PAN verification was unavailable. Using simulated verification.",
                )
                if not result.valid:
                    result = MockInsurerTaggedProvider().validate(
                        id_type=id_type,
                        id_number=id_number,
                        attempt_number=max(2, attempt),
                    )
                    result.valid = True
                    result.match_kind = "full"
                    result.fallback_to_mock = True
        else:
            result = MockInsurerTaggedProvider().validate(
                id_type=id_type, id_number=id_number, attempt_number=attempt
            )
    if result is None:
        result = MockInsurerTaggedProvider().validate(
            id_type=id_type, id_number=id_number, attempt_number=attempt
        )
    customer.id_masked = result.id_masked
    customer.id_type = result.id_type
    customer.id_encrypted = encrypt_secret(id_number) if result.valid or result.match_kind == "partial" else None
    if not result.valid and result.match_kind != "partial":
        customer.id_masked = result.id_masked
    event = PolicyKycEvent(
        booking_request_id=booking.id,
        id_type=result.id_type,
        id_number_masked=result.id_masked,
        validation_mode=result.mode,
        validation_result=(
            "partial" if result.match_kind == "partial" else ("valid" if result.valid else "invalid")
        ),
        attempt_number=attempt,
        demo_mode=result.demo_mode,
        reason=result.reason,
        client_ref_id=result.client_ref_id,
        raw_response=result.raw_response,
        name_match=result.name_match,
        dob_match=result.dob_match,
        pan_status=result.pan_status,
        aadhaar_seeding_status=result.aadhaar_seeding_status,
    )
    db.add(event)
    db.flush()
    booking.kyc_events.append(event)
    booking.kyc_mode_used = result.mode
    booking.status = STATUS_KYC_SIMULATED_VALID if result.valid else STATUS_KYC_PENDING
    details = []
    if result.pan_status:
        details.append(f"PAN status: {result.pan_status}")
    if result.name_match:
        details.append(f"Name match: {result.name_match}")
    if result.dob_match:
        details.append(f"DOB match: {result.dob_match}")
    if result.aadhaar_seeding_status:
        desc = f" ({result.aadhaar_seeding_status_desc})" if result.aadhaar_seeding_status_desc else ""
        details.append(f"Aadhaar seeding: {result.aadhaar_seeding_status}{desc}")
    _assistant(
        db,
        booking,
        (
            f"KYC result: **{'Valid' if result.valid else 'Invalid'}**"
            + (" — partial match" if result.match_kind == "partial" else "")
            + ".\n"
            f"**{result.label}**\n"
            f"ID type: {result.id_type} · Masked ID: {result.id_masked}"
            + (("\n" + "\n".join(details)) if details else "")
            + (f"\n{result.reason}" if result.reason else "")
            + (f"\n{result.user_notice}" if result.user_notice else "")
        ),
        message_type="card",
        payload={
            "kind": "kyc_card",
            "label": result.label,
            "valid": result.valid,
            "id_type": result.id_type,
            "id_masked": result.id_masked,
            "reason": result.reason,
            "name_match": result.name_match,
            "dob_match": result.dob_match,
            "pan_status": result.pan_status,
            "aadhaar_seeding_status": result.aadhaar_seeding_status,
            "match_kind": result.match_kind,
        },
    )
    if result.match_kind == "partial":
        booking.current_step = "confirm_kyc_partial"
        _prompt_for(db, booking, "confirm_kyc_partial")
        return
    if result.valid:
        booking.current_step = "generate_quotes"
        _run_quotes(db, booking, user_id)
        return
    booking.current_step = "collect_id_number"
    retry_msg = "Please re-enter the ID number."
    if result.mode == KYC_MODE_EKO_PAN:
        retry_msg = "Please re-enter the PAN. One live retry is allowed before simulated verification is used."
    else:
        retry_msg = "Please re-enter the ID number. Simulated KYC will accept the retry in this session."
    _assistant(db, booking, retry_msg)


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
        "Here are three **illustrative quotations**. Premiums are not insurer API prices.",
        message_type="quote",
        payload={"kind": "quote_cards", "label": LABEL_DEMO_QUOTE, "quotes": cards},
    )


def _issue_policy(
    db: Session,
    booking: PolicyBookingRequest,
    user_id: int,
    *,
    payment: PolicyPayment | None = None,
) -> None:
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
    policy_ref = f"POLICY_{secrets.token_hex(5).upper()}"
    path = generate_policy_document(
        booking,
        policy_reference=policy_ref,
        issue_on=today,
        expiry_on=expiry,
        watermark=watermark,
        payment=payment,
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
        payment_id=payment.id if payment else None,
    )
    db.add(issued)
    booking.issued_policy = issued
    booking.status = STATUS_ISSUED_DEMO
    booking.current_step = "policy_issued"
    _assistant(
        db,
        booking,
        (
            f"Policy document created.\n"
            f"**{LABEL_DEMO_POLICY}**\n"
            f"Reference: {policy_ref}\n"
            f"{selected.insurer_name} · {selected.package_type} · ₹{float(selected.premium):,.0f}"
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
    _system(
        db,
        booking,
        "Thank you for using the Policy Booking Assistant. Your booking is complete. You can download your policy above.",
    )


class PaymentFlowError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def process_simulated_payment(
    db: Session,
    booking: PolicyBookingRequest,
    user_id: int,
    *,
    payment_method: str,
    card_holder_name: str | None = None,
    card_number: str | None = None,
    expiry: str | None = None,
    cvv: str | None = None,
) -> PolicyBookingRequest:
    method = (payment_method or "").strip().lower()
    if method not in PAYMENT_METHODS:
        raise PaymentFlowError("Please select a valid payment method.")
    can_pay = booking.status == STATUS_QUOTE_SELECTED and booking.current_step == "initiate_payment"
    can_retry = booking.status == STATUS_PAYMENT_CONFIRMED and booking.issued_policy is None
    if not can_pay and not can_retry:
        raise PaymentFlowError("Select a quotation before continuing to payment.")
    selected = next((q for q in (booking.quotes or []) if q.selected), None)
    if not selected:
        raise PaymentFlowError("Select a quotation before continuing to payment.")

    if can_retry and booking.payments:
        payment = booking.payments[-1]
    else:
        holder = (card_holder_name or "").strip()[:255] or None
        last4 = mask_card_last4(card_number)
        expiry_masked = mask_expiry(expiry)
        cvv_masked = "XXX" if (cvv or "").strip() else None
        if method == "cards":
            if not holder or not last4 or not expiry_masked or not cvv_masked:
                raise PaymentFlowError("Please fill in the card details.")

        payment = PolicyPayment(
            booking_request_id=booking.id,
            payment_method=method,
            card_holder_name=holder if method == "cards" else None,
            card_number_masked=last4 if method == "cards" else None,
            expiry_masked=expiry_masked if method == "cards" else None,
            cvv_masked=cvv_masked if method == "cards" else None,
            amount=float(selected.premium),
            status="success",
        )
        db.add(payment)
        db.flush()
        booking.payments.append(payment)
        booking.payment_method = method

    booking.status = STATUS_PAYMENT_CONFIRMED
    booking.current_step = "payment_confirmed"
    logger.info(
        "policy payment simulated booking_request_id=%s payment_method=%s amount=%s",
        booking.id,
        method,
        float(selected.premium),
    )
    _assistant(
        db,
        booking,
        "Payment Successful! Policy issuance in process.",
        message_type="card",
        payload={"kind": "payment_success"},
    )
    try:
        _issue_policy(db, booking, user_id, payment=payment)
    except Exception as exc:
        logger.exception("policy document generation failed booking_request_id=%s", booking.id)
        db.commit()
        raise PaymentFlowError(
            "Error generating policy. Please try again or contact support.",
            status_code=500,
        ) from exc
    db.commit()
    return get_booking_by_session(db, booking.session_id, user_id) or booking


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
                booking.vehicle.blacklist_acknowledged = True
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

    if step == "confirm_blacklist":
        if lowered in {"continue_blacklist", "yes", "y", "continue", "continue anyway", "ok"}:
            if booking.vehicle:
                booking.vehicle.blacklist_acknowledged = True
            return True
        if lowered in {"reset_booking", "no", "n", "start over", "reset"}:
            if booking.vehicle:
                db.delete(booking.vehicle)
                booking.vehicle = None
            booking.current_step = "collect_registration_number"
            booking.status = STATUS_STARTED
            _assistant(db, booking, "Booking reset. " + STEP_PROMPTS["collect_registration_number"])
            return True
        return False

    if step == "confirm_kyc_partial":
        if lowered in {"continue_kyc", "yes", "y", "continue", "ok"}:
            if booking.kyc_events:
                booking.kyc_events[-1].validation_result = "valid"
            booking.status = STATUS_KYC_SIMULATED_VALID
            return True
        if lowered in {"retry_kyc", "no", "n", "re-enter pan", "re-enter"}:
            customer.id_encrypted = None
            customer.id_masked = None
            booking.current_step = "collect_id_number"
            _assistant(db, booking, STEP_PROMPTS["collect_id_number"])
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
                booking.current_step = "initiate_payment"
                return True
            if lowered in {quote.insurer_name.lower(), quote.package_type.lower()}:
                for other in booking.quotes:
                    other.selected = other.id == quote.id
                booking.status = STATUS_QUOTE_SELECTED
                booking.current_step = "initiate_payment"
                return True
        return False

    if step == "initiate_payment":
        _assistant(
            db,
            booking,
            "Please select a payment method on the card above and click Pay Now. Typing here will not process payment.",
        )
        return True

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
        if nxt == "initiate_payment":
            return
        if nxt == "issue_policy":
            if not _payment_succeeded(booking):
                booking.current_step = "initiate_payment"
                return
            _issue_policy(db, booking, user_id)
            continue
        if nxt in {"completed", "policy_issued", "payment_confirmed"}:
            return
        return


def handle_user_message(db: Session, booking: PolicyBookingRequest, text: str, user_id: int) -> PolicyBookingRequest:
    raw = (text or "").strip()
    if not raw:
        _assistant(db, booking, "I did not catch that. " + STEP_PROMPTS.get(booking.current_step, "Please continue."))
        db.commit()
        return booking

    if booking.current_step in {"completed", "policy_issued"}:
        _add_message(db, booking, sender="user", text=raw)
        _assistant(
            db,
            booking,
            "This booking is complete. Start a new booking from the header if you want another journey.",
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
    if nxt not in {"vehicle_lookup", "kyc_simulation", "generate_quotes", "issue_policy", "completed", "policy_issued", "payment_confirmed"}:
        # Avoid duplicate prompts if auto step already asked.
        last = booking.messages[-1] if booking.messages else None
        already = bool(last and last.sender == "assistant" and last.payload)
        already_payment = any(
            (m.payload or {}).get("kind") == "payment_card" for m in (booking.messages or [])
        )
        if nxt == "confirm_vehicle" and already:
            pass
        elif nxt == "confirm_blacklist" and already:
            pass
        elif nxt == "confirm_kyc_partial" and already:
            pass
        elif nxt == "select_quote" and already:
            pass
        elif nxt == "initiate_payment" and already_payment:
            pass
        else:
            _prompt_for(db, booking, nxt)
    db.commit()
    return get_booking_by_session(db, booking.session_id, user_id) or booking
