"""Fernet-encrypted per-user policy module settings (same pattern as BYOK)."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.policy.constants import (
    DEFAULT_WATERMARK,
    KYC_MODE_INSURER,
    KYC_MODE_LOCAL,
    KYC_MODE_MOCK,
)
from app.policy.models import PolicySettings
from app.services.llm.encryption import LlmEncryptionError, mask_api_key

DEFAULTS: dict[str, Any] = {
    "force_demo_fallback": False,
    "kyc_mode": KYC_MODE_MOCK,
    "kyc_tier1_enabled": False,
    "kyc_tier2_enabled": False,
    "quotes_randomized": True,
    "premium_floor_a": 8000.0,
    "premium_floor_b": 12000.0,
    "premium_floor_c": 18000.0,
    "watermark_text": DEFAULT_WATERMARK,
    "show_demo_labels": True,
    "eko_key_override": "",
}


def _fernet() -> Fernet:
    try:
        from app.services.llm.encryption import _fernet as llm_fernet

        return llm_fernet()
    except LlmEncryptionError:
        digest = hashlib.sha256(get_settings().secret_key.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> bytes:
    return _fernet().encrypt(plain.strip().encode("utf-8"))


def decrypt_secret(token: bytes) -> str:
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise LlmEncryptionError("Stored ID could not be decrypted") from exc


def encrypt_payload(data: dict[str, Any]) -> bytes:
    return _fernet().encrypt(json.dumps(data).encode("utf-8"))


def decrypt_payload(token: bytes) -> dict[str, Any]:
    try:
        raw = _fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise LlmEncryptionError("Policy settings could not be decrypted") from exc
    data = json.loads(raw)
    return {**DEFAULTS, **data} if isinstance(data, dict) else dict(DEFAULTS)


def load_settings(db: Session, user_id: int) -> dict[str, Any]:
    row = db.scalar(select(PolicySettings).where(PolicySettings.user_id == user_id))
    if not row:
        return dict(DEFAULTS)
    try:
        return decrypt_payload(row.encrypted_payload)
    except LlmEncryptionError:
        return dict(DEFAULTS)


def save_settings(db: Session, user_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    current = load_settings(db, user_id)
    merged = {**current}
    for key, value in updates.items():
        if key in DEFAULTS:
            merged[key] = value
    row = db.scalar(select(PolicySettings).where(PolicySettings.user_id == user_id))
    blob = encrypt_payload(merged)
    if row:
        row.encrypted_payload = blob
    else:
        db.add(PolicySettings(user_id=user_id, encrypted_payload=blob))
    db.commit()
    return merged


def resolved_kyc_mode(stored: dict[str, Any]) -> tuple[str, str | None]:
    """Return (mode, warning). Non-default modes fall back without required config."""
    requested = stored.get("kyc_mode") or KYC_MODE_MOCK
    if requested == KYC_MODE_MOCK:
        return KYC_MODE_MOCK, None
    if requested == KYC_MODE_INSURER:
        return (
            KYC_MODE_MOCK,
            "Insurer API / DigiLocker is Not Configured. Using Mock Insurer-Tagged.",
        )
    if requested == KYC_MODE_LOCAL:
        tier1 = bool(stored.get("kyc_tier1_enabled"))
        tier2 = bool(stored.get("kyc_tier2_enabled"))
        if not tier1 and not tier2:
            return (
                KYC_MODE_MOCK,
                "Local Extraction Pipeline is Disabled — Demo Mode Only. Using Mock Insurer-Tagged.",
            )
        return (
            KYC_MODE_MOCK,
            "Local OCR / Vision LLM is not enabled and tested on this instance. Using Mock Insurer-Tagged.",
        )
    return KYC_MODE_MOCK, "Unknown KYC mode. Using Mock Insurer-Tagged."


def eko_key_hint() -> str:
    key = (get_settings().eko_vehicle_api_key or "").strip()
    if not key:
        return "Not set"
    return mask_api_key(key)


def public_settings_view(db: Session, user_id: int) -> dict[str, Any]:
    stored = load_settings(db, user_id)
    mode, warning = resolved_kyc_mode(stored)
    env = get_settings()
    return {
        "eko_key_hint": eko_key_hint(),
        "eko_key_configured": bool((env.eko_vehicle_api_key or "").strip()),
        "eko_developer_key_configured": bool((env.eko_developer_key or "").strip()),
        "eko_initiator_configured": bool((env.eko_initiator_id or "").strip()),
        "force_demo_fallback": bool(stored.get("force_demo_fallback")),
        "kyc_mode_requested": stored.get("kyc_mode") or KYC_MODE_MOCK,
        "kyc_mode_active": mode,
        "kyc_warning": warning,
        "kyc_tier1_enabled": False,
        "kyc_tier2_enabled": False,
        "kyc_tier1_label": "Disabled — Demo Mode Only",
        "kyc_tier2_label": "Disabled — Demo Mode Only",
        "quotes_randomized": bool(stored.get("quotes_randomized")),
        "premium_floor_a": float(stored.get("premium_floor_a") or 8000),
        "premium_floor_b": float(stored.get("premium_floor_b") or 12000),
        "premium_floor_c": float(stored.get("premium_floor_c") or 18000),
        "watermark_text": stored.get("watermark_text") or DEFAULT_WATERMARK,
        "show_demo_labels": True,
        "demo_labels_locked": True,
        "demo_labels_note": (
            "Honesty labels stay visible until a live insurer/KYC integration is configured and tested."
        ),
    }
