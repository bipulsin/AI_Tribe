"""User LLM preferences and encrypted provider key storage."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserLlmPreferences, UserLlmProviderKey
from app.services.llm.constants import PROVIDERS, TOGGLE_LABELS
from app.services.llm.encryption import LlmEncryptionError, decrypt_api_key, encrypt_api_key, mask_api_key


def get_or_create_preferences(db: Session, user_id: int) -> UserLlmPreferences:
    prefs = db.get(UserLlmPreferences, user_id)
    if prefs is None:
        prefs = UserLlmPreferences(user_id=user_id)
        db.add(prefs)
        db.flush()
    return prefs


def list_provider_keys(db: Session, user_id: int) -> list[UserLlmProviderKey]:
    return list(
        db.scalars(
            select(UserLlmProviderKey)
            .where(UserLlmProviderKey.user_id == user_id)
            .order_by(UserLlmProviderKey.provider.asc())
        ).all()
    )


def settings_payload(db: Session, user_id: int) -> dict:
    prefs = get_or_create_preferences(db, user_id)
    keys = list_provider_keys(db, user_id)
    configured = {row.provider for row in keys}
    has_key = bool(prefs.active_provider and prefs.active_provider in configured)
    if not prefs.active_provider and keys:
        prefs.active_provider = keys[0].provider
        db.commit()

    return {
        "providers": list(PROVIDERS),
        "active_provider": prefs.active_provider,
        "keys": [
            {"provider": row.provider, "key_hint": row.key_hint, "configured": True}
            for row in keys
        ],
        "has_valid_key": has_key,
        "toggles": {
            "toggle_deepfake": prefs.toggle_deepfake,
            "toggle_vmmr": prefs.toggle_vmmr,
            "toggle_estimation": prefs.toggle_estimation,
            "toggle_fraud": prefs.toggle_fraud,
        },
        "toggle_labels": TOGGLE_LABELS,
        "encryption_configured": _encryption_available(),
    }


def _encryption_available() -> bool:
    try:
        from app.services.llm.encryption import _fernet  # noqa: PLC0415

        _fernet()
        return True
    except Exception:
        return False


def upsert_provider_key(db: Session, user_id: int, provider: str, api_key: str) -> dict:
    if provider not in PROVIDERS:
        raise ValueError("Unknown provider")
    plain = api_key.strip()
    if len(plain) < 8:
        raise ValueError("API key is too short")

    encrypted = encrypt_api_key(plain)
    hint = mask_api_key(plain)
    row = db.scalar(
        select(UserLlmProviderKey).where(
            UserLlmProviderKey.user_id == user_id,
            UserLlmProviderKey.provider == provider,
        )
    )
    if row is None:
        row = UserLlmProviderKey(
            user_id=user_id,
            provider=provider,
            encrypted_key=encrypted,
            key_hint=hint,
        )
        db.add(row)
    else:
        row.encrypted_key = encrypted
        row.key_hint = hint

    prefs = get_or_create_preferences(db, user_id)
    if not prefs.active_provider:
        prefs.active_provider = provider
    db.commit()
    return {"provider": provider, "key_hint": hint, "configured": True}


def remove_provider_key(db: Session, user_id: int, provider: str) -> None:
    row = db.scalar(
        select(UserLlmProviderKey).where(
            UserLlmProviderKey.user_id == user_id,
            UserLlmProviderKey.provider == provider,
        )
    )
    if row:
        db.delete(row)
    prefs = get_or_create_preferences(db, user_id)
    if prefs.active_provider == provider:
        remaining = [k for k in list_provider_keys(db, user_id) if k.provider != provider]
        prefs.active_provider = remaining[0].provider if remaining else None
    db.commit()


def update_preferences(db: Session, user_id: int, payload: dict) -> UserLlmPreferences:
    prefs = get_or_create_preferences(db, user_id)
    if "active_provider" in payload:
        active = payload.get("active_provider")
        if active:
            row = db.scalar(
                select(UserLlmProviderKey).where(
                    UserLlmProviderKey.user_id == user_id,
                    UserLlmProviderKey.provider == active,
                )
            )
            if not row:
                raise ValueError("Active provider has no stored key")
        prefs.active_provider = active
    for field in ("toggle_deepfake", "toggle_vmmr", "toggle_estimation", "toggle_fraud"):
        if field in payload:
            setattr(prefs, field, bool(payload[field]))
    db.commit()
    db.refresh(prefs)
    return prefs


def get_active_api_key(db: Session, user_id: int) -> tuple[str, str] | None:
    prefs = db.get(UserLlmPreferences, user_id)
    if not prefs or not prefs.active_provider:
        return None
    row = db.scalar(
        select(UserLlmProviderKey).where(
            UserLlmProviderKey.user_id == user_id,
            UserLlmProviderKey.provider == prefs.active_provider,
        )
    )
    if not row:
        return None
    try:
        return prefs.active_provider, decrypt_api_key(row.encrypted_key)
    except LlmEncryptionError:
        return None


def toggle_enabled(db: Session, user_id: int, toggle_name: str) -> bool:
    prefs = db.get(UserLlmPreferences, user_id)
    if not prefs:
        return False
    return bool(getattr(prefs, toggle_name, False))
