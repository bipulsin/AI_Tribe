"""Deterministic field extraction for policy booking (regex + existing spaCy NLU)."""

from __future__ import annotations

import re
from datetime import datetime

# Two letters, two digits, one or two letters, four digits (Indian RC).
REGISTRATION_RE = re.compile(r"\b([A-Za-z]{2}\s*\d{2}\s*[A-Za-z]{1,2}\s*\d{4})\b")
PHONE_RE = re.compile(r"\b(?:\+91[\s-]?)?([6-9]\d{9})\b")
PAN_RE = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", re.IGNORECASE)
AADHAAR_RE = re.compile(r"\b(\d{4}[\s-]?\d{4}[\s-]?\d{4})\b")
PINCODE_RE = re.compile(r"\b([1-9]\d{5})\b")
NAME_FOR_RE = re.compile(
    r"\b(?:for|customer|name(?:\s+is)?|insured)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,3})\b"
)
ADDRESS_RE = re.compile(
    r"\b(?:address(?:\s+is)?|at)\s*[:\-]?\s*(.{8,120})$",
    re.IGNORECASE,
)

_DATE_PATTERNS = [
    re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
    re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"),
    re.compile(
        r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b",
        re.IGNORECASE,
    ),
]


def normalize_registration(raw: str) -> str:
    return re.sub(r"\s+", "", (raw or "").upper())


def is_valid_registration(raw: str) -> bool:
    compact = normalize_registration(raw)
    return bool(re.fullmatch(r"[A-Z]{2}\d{2}[A-Z]{1,2}\d{4}", compact))


def is_valid_phone(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return bool(re.fullmatch(r"[6-9]\d{9}", digits))


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    return digits


def is_valid_pan(raw: str) -> bool:
    return bool(PAN_RE.fullmatch((raw or "").strip().upper().replace(" ", "")))


def is_valid_aadhaar(raw: str) -> bool:
    digits = re.sub(r"\D", "", raw or "")
    return len(digits) == 12 and not digits.startswith("0")


def is_valid_pincode(raw: str) -> bool:
    return bool(re.fullmatch(r"[1-9]\d{5}", (raw or "").strip()))


def mask_id_number(raw: str) -> str:
    compact = re.sub(r"\s+", "", raw or "")
    if len(compact) <= 4:
        return "****"
    return f"{'*' * max(4, len(compact) - 4)}{compact[-4:]}"


def last_four(raw: str) -> str:
    compact = re.sub(r"[\s-]", "", raw or "")
    return compact[-4:] if compact else ""


def parse_dob(raw: str) -> str | None:
    text = (raw or "").strip()
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d/%m/%y",
        "%d-%m-%y",
        "%m/%d/%Y",
        "%d %b %Y",
        "%d %B %Y",
    ):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_policy_fields(text: str) -> dict[str, str]:
    """Pull booking fields from free text. Does not require NLU models."""
    raw = (text or "").strip()
    out: dict[str, str] = {}
    if not raw:
        return out

    reg_match = REGISTRATION_RE.search(raw)
    if reg_match and is_valid_registration(reg_match.group(1)):
        out["registration_number"] = normalize_registration(reg_match.group(1))

    phone_match = PHONE_RE.search(raw)
    if phone_match:
        out["phone"] = phone_match.group(1)

    pan_match = PAN_RE.search(raw)
    if pan_match:
        out["id_type"] = "PAN"
        out["id_number"] = pan_match.group(1).upper()

    if "id_number" not in out:
        aad_match = AADHAAR_RE.search(raw)
        if aad_match and is_valid_aadhaar(aad_match.group(1)):
            out["id_type"] = "Aadhaar"
            out["id_number"] = re.sub(r"\D", "", aad_match.group(1))

    pin_match = PINCODE_RE.search(raw)
    if pin_match:
        out["pincode"] = pin_match.group(1)

    for pattern in _DATE_PATTERNS:
        match = pattern.search(raw)
        if match:
            parsed = parse_dob(match.group(1))
            if parsed:
                out["dob"] = parsed
                break

    name_match = NAME_FOR_RE.search(raw)
    if name_match:
        out["customer_name"] = name_match.group(1).strip()

    lowered = raw.lower().strip()
    if lowered in {"pan", "aadhaar", "aadhar"}:
        out["id_type"] = "PAN" if lowered == "pan" else "Aadhaar"
    if lowered in {"male", "female", "other"}:
        out["gender"] = lowered.title()
    if lowered in {"yes", "y", "previous policy yes", "has previous policy"}:
        out["previous_policy"] = "yes"
    if lowered in {"no", "n", "no previous policy", "fresh", "new"}:
        out["previous_policy"] = "no"

    addr_match = ADDRESS_RE.search(raw)
    if addr_match and len(raw.split()) >= 3 and "registration" not in lowered:
        addr = addr_match.group(1).strip()
        if not is_valid_registration(addr) and not PHONE_RE.search(addr):
            out["address"] = addr[:200]

    return out


def enrich_with_nlu(text: str, fields: dict[str, str]) -> dict[str, str]:
    """Use existing MiniLM/spaCy pipeline for PERSON names when regex missed."""
    merged = dict(fields)
    if merged.get("customer_name"):
        return merged
    try:
        from app.core.config import get_settings
        from app.services.chat.nlu.entities import extract_entities

        settings = get_settings()
        root = settings.chat_nlu_path if settings.chat_nlu_enabled else None
        entities = extract_entities(text, root=root)
        person = entities.get("surveyor_name") or entities.get("actor_name")
        if person and len(person.split()) <= 4:
            merged["customer_name"] = person.strip()[:128]
    except Exception:
        pass
    return merged


def next_collection_step_from_fields(fields: dict) -> str:
    """Pure helper for tests: first missing collection step given a field dict."""
    if not fields.get("registration_number"):
        return "collect_registration_number"
    if not fields.get("vehicle_confirmed"):
        return "confirm_vehicle"
    if not fields.get("customer_name"):
        return "collect_customer_name"
    if not fields.get("phone"):
        return "collect_phone"
    if not fields.get("id_type"):
        return "collect_id_type"
    if not fields.get("id_number"):
        return "collect_id_number"
    if not fields.get("dob"):
        return "collect_dob"
    if not fields.get("gender"):
        return "collect_gender"
    if not fields.get("address"):
        return "collect_address"
    if not fields.get("pincode"):
        return "collect_pincode"
    if fields.get("previous_policy") is None:
        return "collect_previous_policy"
    if not fields.get("kyc_valid"):
        return "kyc_simulation"
    if not fields.get("quotes"):
        return "generate_quotes"
    if not fields.get("quote_selected"):
        return "select_quote"
    if not fields.get("issued"):
        return "issue_policy"
    return "completed"
