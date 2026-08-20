"""Copy pydantic-loaded EKO settings into os.environ for get_eko_headers()."""

from __future__ import annotations

import os

from app.core.config import get_settings


def prepare_eko_environ() -> None:
    """Fill missing EKO_* process env from Settings (.env / compose)."""
    settings = get_settings()
    access = (settings.eko_access_key or settings.eko_vehicle_api_key or "").strip()
    developer = (settings.eko_developer_key or "").strip()
    initiator = (settings.eko_initiator_id or "").strip()
    base = (settings.eko_base_url or "").strip()
    if access and not (os.getenv("EKO_ACCESS_KEY") or "").strip():
        os.environ["EKO_ACCESS_KEY"] = access
    if developer and not (os.getenv("EKO_DEVELOPER_KEY") or "").strip():
        os.environ["EKO_DEVELOPER_KEY"] = developer
    if initiator and not (os.getenv("EKO_INITIATOR_ID") or "").strip():
        os.environ["EKO_INITIATOR_ID"] = initiator
    if base and not (os.getenv("EKO_BASE_URL") or "").strip():
        os.environ["EKO_BASE_URL"] = base


def eko_configured() -> bool:
    prepare_eko_environ()
    settings = get_settings()
    access = (settings.eko_access_key or settings.eko_vehicle_api_key or os.getenv("EKO_ACCESS_KEY") or "").strip()
    developer = (settings.eko_developer_key or os.getenv("EKO_DEVELOPER_KEY") or "").strip()
    initiator = (settings.eko_initiator_id or os.getenv("EKO_INITIATOR_ID") or "").strip()
    return bool(access and developer and initiator)


def mask_initiator(raw: str) -> str:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) < 4:
        return "Not set"
    return f"XXXX{digits[-4:]}"
