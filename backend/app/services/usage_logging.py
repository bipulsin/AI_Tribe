"""Classify routes and persist lightweight usage events."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.models.usage_event import UsageEvent

logger = logging.getLogger("ai_tribe.usage")

# Paths we never log (noise / internals / binary).
_SKIP_PREFIXES = (
    "/static/",
    "/uploads/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
    "/favicon",
)

_SKIP_EXACT = {"/", "/login"}

# High-frequency streaming — skip to avoid flooding.
_SKIP_STREAM_SUFFIX = "/stream"

_CLAIM_ID_RE = re.compile(r"/claims/(\d+)(?:/|$)")
_API_CLAIM_RE = re.compile(r"/api/v1/external/claims/([^/]+)")


def should_skip_path(path: str, method: str) -> bool:
    if method.upper() in {"OPTIONS", "HEAD"}:
        return True
    if path in _SKIP_EXACT:
        return True
    for prefix in _SKIP_PREFIXES:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return True
    # SSE / live pipeline stream
    if path.endswith(_SKIP_STREAM_SUFFIX):
        return True
    if path.startswith("/api/suggest/"):
        return True
    return False


def classify_route(method: str, path: str) -> tuple[str, str]:
    """Return (event_type, feature_area) for a request."""
    m = method.upper()
    p = path

    if p in {"/auth/login"} or p.endswith("/auth/login"):
        return "login", "auth"
    if p.startswith("/auth/logout"):
        return "logout", "auth"

    if p.startswith("/chat") or p.startswith("/api/chat/"):
        if "/upload" in p:
            return "chat_upload", "chat"
        if p.endswith("/message") or "/message" in p:
            return "chat_message", "chat"
        return "chat_page", "chat"

    if p.startswith("/api/v1/external/") or p.startswith("/settings/api-marketplace") or p.startswith(
        "/api/marketplace/"
    ):
        if "/claims/submit" in p:
            return "api_submit_claim", "api_marketplace"
        if "/images" in p:
            return "api_submit_images", "api_marketplace"
        if "/assessment" in p:
            return "api_assessment", "api_marketplace"
        if "/estimate" in p:
            return "api_estimate", "api_marketplace"
        if "/policy-details" in p:
            return "api_policy_details", "api_marketplace"
        if "/salesforce/leads" in p:
            return "api_salesforce_leads", "api_marketplace"
        if "/connectors/salesforce" in p:
            return "api_connector_config", "api_marketplace"
        if p.startswith("/api/marketplace/token"):
            return "api_token_manage", "api_marketplace"
        if p.startswith("/api/marketplace/subscribe"):
            return "api_subscribe", "api_marketplace"
        if p.startswith("/api/marketplace/chains"):
            return "api_chain", "api_marketplace"
        return "api_marketplace_call", "api_marketplace"

    if p.startswith("/lab/") or p.startswith("/api/lab/"):
        return "vmmr_labeling", "lab_vmmr"

    if p.startswith("/api/admin/") or p.startswith("/admin/"):
        return "admin_action", "admin"

    if p == "/claims" and m == "POST":
        return "submit_claim", "form_ui"
    if p == "/claims/new":
        return "claim_form_view", "form_ui"
    if "/processing" in p:
        return "damage_assessment", "form_ui"
    if "/estimate" in p:
        return "estimate_view", "form_ui"
    if p.startswith("/api/claims/search"):
        return "lookup_claim", "form_ui"
    if p.startswith("/claims/") and m == "GET":
        return "claim_view", "form_ui"

    if p.startswith("/api/user/") or p.startswith("/api/profile"):
        return "profile_settings", "settings"

    return "page_view" if m == "GET" else "api_call", "other"


def extract_metadata(path: str) -> dict[str, Any] | None:
    meta: dict[str, Any] = {}
    m = _CLAIM_ID_RE.search(path)
    if m:
        meta["claim_id"] = int(m.group(1))
    m2 = _API_CLAIM_RE.search(path)
    if m2 and m2.group(1) not in {"submit"}:
        meta["claim_ref"] = m2.group(1)[:64]
    return meta or None


def record_usage_event(
    db: Session,
    *,
    user_id: int | None,
    username_snapshot: str | None,
    event_type: str,
    feature_area: str,
    endpoint_or_route: str,
    session_id: str | None = None,
    ip_address: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert one usage row. Caller owns commit or we commit here for middleware."""
    row = UsageEvent(
        user_id=user_id,
        username_snapshot=(username_snapshot or None) and str(username_snapshot)[:128],
        event_type=event_type[:64],
        feature_area=feature_area[:64],
        endpoint_or_route=endpoint_or_route[:256],
        session_id=(session_id or None) and str(session_id)[:64],
        ip_address=(ip_address or None) and str(ip_address)[:64],
        metadata_json=metadata,
    )
    db.add(row)
