"""Fernet encryption for user LLM API keys at rest."""

from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("ai_tribe.llm")


class LlmEncryptionError(RuntimeError):
    pass


def _fernet() -> Fernet:
    raw = os.environ.get("LLM_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise LlmEncryptionError("LLM_ENCRYPTION_KEY is not configured on the server")
    try:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    except Exception as exc:
        raise LlmEncryptionError("LLM_ENCRYPTION_KEY is invalid") from exc


def encrypt_api_key(plain: str) -> bytes:
    return _fernet().encrypt(plain.strip().encode("utf-8"))


def decrypt_api_key(token: bytes) -> str:
    try:
        return _fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise LlmEncryptionError("Stored API key could not be decrypted") from exc


def mask_api_key(plain: str) -> str:
    key = plain.strip()
    if len(key) <= 8:
        return "••••••••"
    return f"{key[:3]}...{key[-4:]}"
