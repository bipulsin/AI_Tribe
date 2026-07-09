"""BYOK LLM settings API — preferences, encrypted keys, and connection tests."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User, UserLlmProviderKey
from app.services.llm import providers
from app.services.llm.constants import PROVIDERS
from app.services.llm.encryption import LlmEncryptionError, decrypt_api_key
from app.services.llm.settings import (
    remove_provider_key,
    settings_payload,
    update_preferences,
    upsert_provider_key,
)

router = APIRouter(tags=["llm-settings"])


def _current_user(request: Request, db: Session) -> User | JSONResponse:
    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    user = db.get(User, user_id)
    if not user:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return user


@router.get("/api/user/llm-settings")
async def get_llm_settings(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    return settings_payload(db, user.id)


@router.put("/api/user/llm-settings")
async def put_llm_settings(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    body = await request.json()
    try:
        update_preferences(db, user.id, body)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return settings_payload(db, user.id)


@router.post("/api/user/llm-settings/keys")
async def post_llm_key(request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    body = await request.json()
    provider = (body.get("provider") or "").strip().lower()
    api_key = body.get("api_key") or ""
    if provider not in PROVIDERS:
        return JSONResponse({"detail": "Unknown provider"}, status_code=400)
    if not api_key.strip():
        return JSONResponse({"detail": "API key is required"}, status_code=400)
    try:
        row = upsert_provider_key(db, user.id, provider, api_key)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except LlmEncryptionError:
        return JSONResponse(
            {"detail": "Server encryption is not configured for API key storage"},
            status_code=503,
        )
    return {"key": row, "settings": settings_payload(db, user.id)}


@router.delete("/api/user/llm-settings/keys/{provider}")
async def delete_llm_key(provider: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    name = provider.strip().lower()
    if name not in PROVIDERS:
        return JSONResponse({"detail": "Unknown provider"}, status_code=400)
    remove_provider_key(db, user.id, name)
    return settings_payload(db, user.id)


@router.post("/api/user/llm-settings/keys/{provider}/test")
async def test_llm_key(provider: str, request: Request, db: Session = Depends(get_db)):
    user = _current_user(request, db)
    if isinstance(user, JSONResponse):
        return user
    name = provider.strip().lower()
    if name not in PROVIDERS:
        return JSONResponse({"detail": "Unknown provider"}, status_code=400)

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    api_key = (body.get("api_key") or "").strip()

    if not api_key:
        row = db.scalar(
            select(UserLlmProviderKey).where(
                UserLlmProviderKey.user_id == user.id,
                UserLlmProviderKey.provider == name,
            )
        )
        if not row:
            return JSONResponse({"detail": "No stored key for this provider"}, status_code=404)
        try:
            api_key = decrypt_api_key(row.encrypted_key)
        except LlmEncryptionError:
            return JSONResponse(
                {"detail": "Stored key could not be decrypted on this server"},
                status_code=503,
            )

    ok, message = providers.test_connection(name, api_key)
    status = 200 if ok else 400
    return JSONResponse({"ok": ok, "message": message}, status_code=status)
