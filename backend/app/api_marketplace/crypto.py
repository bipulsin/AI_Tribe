"""Symmetric encryption helpers for re-showable API tokens."""

from __future__ import annotations

import hashlib
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken

from app.api_marketplace.catalog import DEFAULT_VALIDITY_DAYS


class TokenCryptoError(RuntimeError):
    pass


def _fernet() -> Fernet:
    raw = (
        os.environ.get("API_TOKEN_ENCRYPTION_KEY", "").strip()
        or os.environ.get("LLM_ENCRYPTION_KEY", "").strip()
    )
    if not raw:
        raise TokenCryptoError(
            "API_TOKEN_ENCRYPTION_KEY (or LLM_ENCRYPTION_KEY) is not configured"
        )
    try:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except Exception as exc:
        raise TokenCryptoError("API token encryption key is invalid") from exc


def hash_token(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def encrypt_token(plain: str) -> bytes:
    return _fernet().encrypt(plain.encode("utf-8"))


def decrypt_token(blob: bytes) -> str:
    try:
        return _fernet().decrypt(blob).decode("utf-8")
    except InvalidToken as exc:
        raise TokenCryptoError("Stored API token could not be decrypted") from exc


def generate_live_token() -> str:
    """Format: atr_live_<32 url-safe chars>."""
    return f"atr_live_{secrets.token_urlsafe(24)}"


def token_prefix(plain: str, *, length: int = 12) -> str:
    return plain[:length]


def mint_upload_token(*, claim_no: str, user_id: int, ttl_hours: int = 24) -> str:
    """Short-lived Fernet payload scoped to claim_no + user_id."""
    import json
    from datetime import datetime, timedelta, timezone

    payload = {
        "claim_no": claim_no,
        "user_id": user_id,
        "exp": (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat(),
        "nonce": secrets.token_hex(8),
    }
    return _fernet().encrypt(json.dumps(payload).encode("utf-8")).decode("utf-8")


def parse_upload_token(token: str) -> dict:
    import json
    from datetime import datetime, timezone

    try:
        data = json.loads(_fernet().decrypt(token.encode("utf-8")).decode("utf-8"))
    except Exception as exc:
        raise TokenCryptoError("Invalid upload token") from exc
    exp = data.get("exp")
    if not exp:
        raise TokenCryptoError("Invalid upload token")
    expires = datetime.fromisoformat(exp)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise TokenCryptoError("Upload token expired")
    return data


__all__ = [
    "DEFAULT_VALIDITY_DAYS",
    "TokenCryptoError",
    "decrypt_token",
    "encrypt_token",
    "generate_live_token",
    "hash_token",
    "mint_upload_token",
    "parse_upload_token",
    "token_prefix",
]
