"""Vehicle RC lookup: EKO live provider + demo fallback behind a shared interface."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import get_settings
from app.policy.constants import LABEL_DEMO_FALLBACK, LABEL_LIVE_VAHAN, SOURCE_DEMO_FALLBACK, SOURCE_LIVE_API
from app.policy.extraction import normalize_registration

logger = logging.getLogger("ai_tribe.policy.vehicle")

_CACHE: dict[str, tuple[float, "VehicleLookupResult"]] = {}
_CACHE_TTL_SECONDS = 3600


@dataclass
class VehicleLookupResult:
    registration_number: str
    make: str
    model: str
    year: int | None
    color: str
    fuel_type: str
    owner_name: str
    source: str
    source_label: str
    raw_payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def display_year(self) -> str:
        return str(self.year) if self.year else "—"


class VehicleLookupProvider(Protocol):
    def lookup(self, registration_number: str) -> VehicleLookupResult: ...


FALLBACK_BY_PREFIX: dict[str, dict[str, Any]] = {
    "MH": {"make": "Maruti", "model": "Swift", "year": 2021, "color": "White", "fuel_type": "Petrol", "owner_name": "Demo Owner"},
    "DL": {"make": "Hyundai", "model": "Creta", "year": 2022, "color": "Silver", "fuel_type": "Diesel", "owner_name": "Demo Owner"},
    "KA": {"make": "Toyota", "model": "Innova", "year": 2020, "color": "Grey", "fuel_type": "Diesel", "owner_name": "Demo Owner"},
    "TN": {"make": "Tata", "model": "Nexon", "year": 2023, "color": "Blue", "fuel_type": "Petrol", "owner_name": "Demo Owner"},
}
GENERIC_FALLBACK = {
    "make": "Demo Make",
    "model": "Generic Hatchback",
    "year": 2019,
    "color": "Red",
    "fuel_type": "Petrol",
    "owner_name": "Demo Owner",
}


class DemoFallbackProvider:
    def lookup(self, registration_number: str) -> VehicleLookupResult:
        reg = normalize_registration(registration_number)
        prefix = reg[:2]
        data = FALLBACK_BY_PREFIX.get(prefix, GENERIC_FALLBACK)
        payload = {"provider": "demo_fallback", "prefix": prefix, **data}
        logger.info("policy vehicle lookup source=demo_fallback registration=%s", reg)
        return VehicleLookupResult(
            registration_number=reg,
            make=data["make"],
            model=data["model"],
            year=data["year"],
            color=data["color"],
            fuel_type=data["fuel_type"],
            owner_name=data["owner_name"],
            source=SOURCE_DEMO_FALLBACK,
            source_label=LABEL_DEMO_FALLBACK,
            raw_payload=payload,
        )


def _eko_secret_headers(access_key: str) -> dict[str, str]:
    timestamp = str(int(time.time() * 1000))
    encoded_key = base64.b64encode(access_key.encode("utf-8")).decode("ascii")
    secret = hmac.new(encoded_key.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256)
    return {
        "secret-key": base64.b64encode(secret.digest()).decode("ascii"),
        "secret-key-timestamp": timestamp,
        "content-type": "application/json",
    }


def _year_from_eko(data: dict[str, Any]) -> int | None:
    for key in ("vehicle_manufacturing_month_year", "reg_date", "manufacture_year", "year"):
        raw = data.get(key)
        if not raw:
            continue
        text = str(raw)
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 4:
            try:
                year = int(digits[-4:] if len(digits) > 4 else digits[:4])
                if 1980 <= year <= 2100:
                    return year
            except ValueError:
                continue
        try:
            year = int(text[:4])
            if 1980 <= year <= 2100:
                return year
        except ValueError:
            continue
    return None


class EkoVahanProvider:
    def lookup(self, registration_number: str) -> VehicleLookupResult:
        settings = get_settings()
        access_key = (settings.eko_vehicle_api_key or "").strip()
        developer_key = (settings.eko_developer_key or "").strip()
        initiator_id = (settings.eko_initiator_id or "").strip()
        if not access_key:
            raise RuntimeError("EKO_VEHICLE_API_KEY is not configured")
        if not developer_key or not initiator_id:
            raise RuntimeError(
                "EKO live lookup needs EKO_DEVELOPER_KEY and EKO_INITIATOR_ID in addition to the access key"
            )

        reg = normalize_registration(registration_number)
        url = settings.eko_base_url.rstrip("/") + settings.eko_rc_path
        headers = _eko_secret_headers(access_key)
        headers["developer_key"] = developer_key
        body = {
            "initiator_id": initiator_id,
            "vehicle_number": reg,
            "client_ref_id": f"atr{int(time.time())}"[:20],
        }
        with httpx.Client(timeout=12.0) as client:
            response = client.post(url, json=body, headers=headers)
        payload: dict[str, Any]
        try:
            payload = response.json()
        except Exception:
            payload = {"status_code": response.status_code, "text": response.text[:2000]}
        if response.status_code >= 400:
            raise RuntimeError(f"EKO HTTP {response.status_code}")
        status = payload.get("status")
        if status not in (0, "0", "success", "SUCCESS", None):
            message = payload.get("message") or "EKO lookup failed"
            if payload.get("data"):
                pass
            else:
                raise RuntimeError(str(message))
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        make = str(
            data.get("vehicle_manufacturer_name")
            or data.get("maker")
            or data.get("make")
            or ""
        ).strip()
        model = str(data.get("model") or data.get("vehicle_model") or "").strip()
        if not make and not model:
            raise RuntimeError("EKO response did not include vehicle make/model")
        logger.info("policy vehicle lookup source=live_api registration=%s", reg)
        return VehicleLookupResult(
            registration_number=reg,
            make=make or "Unknown",
            model=model or "Unknown",
            year=_year_from_eko(data),
            color=str(data.get("vehicle_color") or data.get("color") or "").strip() or "—",
            fuel_type=str(data.get("fuel_type") or "").strip() or "—",
            owner_name=str(data.get("owner") or data.get("owner_name") or "").strip() or "—",
            source=SOURCE_LIVE_API,
            source_label=LABEL_LIVE_VAHAN,
            raw_payload=payload if isinstance(payload, dict) else {"raw": str(payload)},
        )


def lookup_vehicle(registration_number: str, *, force_fallback: bool = False) -> VehicleLookupResult:
    reg = normalize_registration(registration_number)
    now = time.time()
    cached = _CACHE.get(reg)
    if cached and cached[0] > now and not force_fallback:
        return cached[1]

    fallback = DemoFallbackProvider()
    if force_fallback:
        result = fallback.lookup(reg)
        _CACHE[reg] = (now + _CACHE_TTL_SECONDS, result)
        return result

    try:
        result = EkoVahanProvider().lookup(reg)
    except Exception as exc:
        logger.warning("EKO vehicle lookup failed (%s) — using demo fallback", exc)
        result = fallback.lookup(reg)
        result.error = str(exc)[:240]
        result.raw_payload = {
            **(result.raw_payload or {}),
            "live_error": str(exc)[:240],
        }
    _CACHE[reg] = (now + _CACHE_TTL_SECONDS, result)
    return result
