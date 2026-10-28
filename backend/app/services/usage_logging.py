"""Classify routes and persist lightweight usage events."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

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

    if p.startswith("/policy"):
        if "/crm" in p:
            return "policy_crm", "policy"
        if "/settings" in p:
            return "policy_settings", "policy"
        if "/chat/message" in p:
            return "policy_chat_message", "policy"
        if "/vehicle" in p:
            return "policy_vehicle_lookup", "policy"
        if "/kyc" in p:
            return "policy_kyc", "policy"
        if "/quotes" in p:
            return "policy_quotes", "policy"
        if "/issue" in p or "/document" in p:
            return "policy_issue", "policy"
        return "policy_page", "policy"

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


# Query / form keys that must never be stored verbatim.
_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "csrf",
    "session",
)

# Metadata keys used for bookkeeping — not shown as "data entered".
_META_INTERNAL_KEYS = frozenset({"source", "search_params"})

_FEATURE_AREA_LABELS = {
    "chat": "Chat",
    "form_ui": "Claims form",
    "api_marketplace": "API Marketplace",
    "lab_vmmr": "Lab VMMR",
    "admin": "Admin",
    "auth": "Auth",
    "settings": "Settings",
    "policy": "Policy",
    "other": "Other",
}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(frag in lowered for frag in _SENSITIVE_KEY_FRAGMENTS)


def _sanitize_param_value(key: str, value: Any, *, max_len: int = 200) -> str:
    if _is_sensitive_key(key):
        return "[redacted]"
    text = "" if value is None else str(value)
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text


def extract_metadata(
    path: str,
    query_params: Any | None = None,
) -> dict[str, Any] | None:
    """Build small JSONB metadata for a request.

    Includes path-derived ids and sanitized query-string ``search_params``.
    Never stores request bodies or secret material.
    """
    meta: dict[str, Any] = {}
    m = _CLAIM_ID_RE.search(path)
    if m:
        meta["claim_id"] = int(m.group(1))
    m2 = _API_CLAIM_RE.search(path)
    if m2 and m2.group(1) not in {"submit"}:
        meta["claim_ref"] = m2.group(1)[:64]

    search: dict[str, str] = {}
    if query_params is not None:
        items: list[tuple[Any, Any]] = []
        if hasattr(query_params, "multi_items"):
            try:
                items = list(query_params.multi_items())
            except Exception:
                items = []
        elif hasattr(query_params, "items") and not isinstance(query_params, (list, tuple)):
            try:
                items = list(query_params.items())
            except Exception:
                items = []
        elif isinstance(query_params, (list, tuple)):
            items = list(query_params)
        for key, value in items:
            k = str(key)
            if not k:
                continue
            search[k] = _sanitize_param_value(k, value)
    if search:
        meta["search_params"] = search

    return meta or None


def feature_area_label(feature_area: str | None) -> str:
    area = (feature_area or "other").strip() or "other"
    return _FEATURE_AREA_LABELS.get(area, area.replace("_", " ").title())


def page_module_label(
    *,
    feature_area: str | None,
    event_type: str | None,
    endpoint_or_route: str | None = None,
) -> str:
    """Human-readable page/module for the usability detail table."""
    area = feature_area_label(feature_area)
    et = (event_type or "").strip().replace("legacy_", "").replace("_", " ")
    if et:
        return f"{area} · {et}"
    route = (endpoint_or_route or "").strip()
    if route:
        return f"{area} · {route}"
    return area


def format_data_entered(metadata: dict[str, Any] | None) -> str | None:
    """Surface non-search metadata as a calm key=value summary."""
    if not isinstance(metadata, dict) or not metadata:
        return None
    parts: list[str] = []
    for key, value in metadata.items():
        if key in _META_INTERNAL_KEYS:
            continue
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            continue
        parts.append(f"{key}={_sanitize_param_value(str(key), value, max_len=120)}")
    return ", ".join(parts) if parts else None


def format_search_params(metadata: dict[str, Any] | None) -> str | None:
    """Format stored query/search parameters for display."""
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("search_params")
    if isinstance(raw, dict) and raw:
        return ", ".join(
            f"{k}={_sanitize_param_value(str(k), v, max_len=120)}" for k, v in raw.items()
        )
    if isinstance(raw, str) and raw.strip():
        return raw.strip()[:240]
    # Some legacy rows may stash a lone ``q`` / ``query`` at the top level.
    for key in ("q", "query", "search", "claim_no", "claim_reference"):
        if key in metadata and metadata[key] not in (None, ""):
            return f"{key}={_sanitize_param_value(key, metadata[key], max_len=120)}"
    return None


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
    from app.models.usage_event import UsageEvent

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
