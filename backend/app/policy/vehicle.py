"""Vehicle RC lookup: EKO live provider + fallback behind a shared interface."""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import get_settings
from app.policy.constants import LABEL_DEMO_FALLBACK, LABEL_LIVE_VAHAN, SOURCE_DEMO_FALLBACK, SOURCE_LIVE_API
from app.policy.eko_runtime import eko_configured, prepare_eko_environ
from app.policy.extraction import is_valid_registration, normalize_registration
from app.services.eko_auth import get_eko_headers, get_eko_initiator_id

logger = logging.getLogger("ai_tribe.policy.vehicle")

_CACHE: dict[str, tuple[float, "VehicleLookupResult"]] = {}
_CACHE_TTL_SECONDS = 24 * 3600
_TIMEOUT_SECONDS = 10.0

BLACKLIST_TOKENS = {"Y", "YES", "BL", "BLACKLIST", "BLACKLISTED", "TRUE", "1"}


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
    client_ref_id: str | None = None
    rc_status: str | None = None
    insurance_validity: str | None = None
    blacklist_status: str | None = None
    blacklisted: bool = False
    not_found: bool = False
    timed_out: bool = False
    user_notice: str | None = None
    response_status_id: int | None = None

    @property
    def display_year(self) -> str:
        return str(self.year) if self.year else "—"


class VehicleLookupProvider(Protocol):
    def lookup(self, registration_number: str) -> VehicleLookupResult: ...


FALLBACK_BY_PREFIX: dict[str, dict[str, Any]] = {
    "MH": {"make": "Maruti", "model": "Swift", "year": 2021, "color": "White", "fuel_type": "Petrol", "owner_name": "Sample Owner"},
    "DL": {"make": "Hyundai", "model": "Creta", "year": 2022, "color": "Silver", "fuel_type": "Diesel", "owner_name": "Sample Owner"},
    "KA": {"make": "Toyota", "model": "Innova", "year": 2020, "color": "Grey", "fuel_type": "Diesel", "owner_name": "Sample Owner"},
    "TN": {"make": "Tata", "model": "Nexon", "year": 2023, "color": "Blue", "fuel_type": "Petrol", "owner_name": "Sample Owner"},
    "HR": {"make": "Hyundai", "model": "i20", "year": 2022, "color": "White", "fuel_type": "Petrol", "owner_name": "Sample Owner"},
}
GENERIC_FALLBACK = {
    "make": "Generic Make",
    "model": "Generic Hatchback",
    "year": 2019,
    "color": "Red",
    "fuel_type": "Petrol",
    "owner_name": "Sample Owner",
}


def _cache_key(registration: str, session_id: str | None) -> str:
    return f"{session_id or '-'}:{registration}"


def make_vehicle_client_ref() -> str:
    return f"VEH{int(time.time())}{secrets.token_hex(2)}"[:20]


def is_blacklist_flag(value: Any) -> bool:
    text = str(value or "").strip().upper()
    if not text or text in {"N", "NO", "NA", "NONE", "-", "FALSE", "0"}:
        return False
    if text in BLACKLIST_TOKENS:
        return True
    return "BLACK" in text


def _year_from_eko(data: dict[str, Any]) -> int | None:
    for key in (
        "year_of_manufacture",
        "vehicle_manufacturing_month_year",
        "reg_date",
        "manufacture_year",
        "year",
    ):
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


def _status_id(payload: dict[str, Any]) -> int | None:
    raw = payload.get("response_status_id", payload.get("status"))
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        text = str(raw).strip().upper()
        if text in {"SUCCESS", "OK"}:
            return 0
        return None


class DemoFallbackProvider:
    def lookup(self, registration_number: str, *, client_ref_id: str | None = None) -> VehicleLookupResult:
        reg = normalize_registration(registration_number)
        prefix = reg[:2]
        data = FALLBACK_BY_PREFIX.get(prefix, GENERIC_FALLBACK)
        payload = {"provider": "demo_fallback", "prefix": prefix, **data}
        logger.info("policy vehicle lookup source=demo_fallback registration=%s client_ref_id=%s", reg, client_ref_id)
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
            client_ref_id=client_ref_id,
        )


class EkoVahanProvider:
    def lookup(self, registration_number: str, *, client_ref_id: str | None = None) -> VehicleLookupResult:
        reg = normalize_registration(registration_number)
        if not is_valid_registration(reg):
            return VehicleLookupResult(
                registration_number=reg,
                make="",
                model="",
                year=None,
                color="",
                fuel_type="",
                owner_name="",
                source="",
                source_label="",
                error="invalid_format",
                user_notice="That registration number format is not valid. Please re-enter it.",
            )
        prepare_eko_environ()
        settings = get_settings()
        if not eko_configured():
            raise RuntimeError("EKO live lookup needs EKO_ACCESS_KEY, EKO_DEVELOPER_KEY, and EKO_INITIATOR_ID")

        ref = client_ref_id or make_vehicle_client_ref()
        headers_full = get_eko_headers()
        base_url = headers_full.pop("base-url")
        url = base_url + settings.eko_rc_path
        body = {
            "initiator_id": get_eko_initiator_id(),
            "vehicle_number": reg,
            "client_ref_id": ref,
        }
        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                response = client.post(url, json=body, headers=headers_full)
        except httpx.TimeoutException:
            logger.warning(
                "EKO vehicle-rc timeout endpoint=vehicle-rc client_ref_id=%s",
                ref,
            )
            result = DemoFallbackProvider().lookup(reg, client_ref_id=ref)
            result.timed_out = True
            result.error = "timeout"
            return result
        except Exception as exc:
            logger.error(
                "EKO vehicle-rc network error endpoint=vehicle-rc client_ref_id=%s err=%s",
                ref,
                type(exc).__name__,
            )
            result = DemoFallbackProvider().lookup(reg, client_ref_id=ref)
            result.error = type(exc).__name__
            return result

        try:
            payload = response.json()
        except Exception:
            payload = {"http_status": response.status_code, "text": (response.text or "")[:2000]}

        status_id = _status_id(payload) if isinstance(payload, dict) else None
        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("message") or payload.get("response_type") or "")[:240]

        if response.status_code != 200:
            logger.warning(
                "EKO vehicle-rc HTTP %s endpoint=vehicle-rc client_ref_id=%s body=%s",
                response.status_code,
                ref,
                str(payload)[:400],
            )
            result = DemoFallbackProvider().lookup(reg, client_ref_id=ref)
            result.error = f"http_{response.status_code}"
            result.response_status_id = status_id
            return result

        if status_id == 1:
            logger.info(
                "EKO vehicle-rc not_found endpoint=vehicle-rc client_ref_id=%s response_status_id=1",
                ref,
            )
            return VehicleLookupResult(
                registration_number=reg,
                make="",
                model="",
                year=None,
                color="",
                fuel_type="",
                owner_name="",
                source="",
                source_label="",
                raw_payload=payload if isinstance(payload, dict) else {"raw": str(payload)},
                client_ref_id=ref,
                not_found=True,
                response_status_id=1,
                user_notice=(
                    "That registration number could not be verified in VAHAN. "
                    "Please double-check and resubmit."
                ),
            )

        if status_id == 2:
            logger.critical(
                "EKO vehicle-rc authentication error endpoint=vehicle-rc client_ref_id=%s response_status_id=2",
                ref,
            )
            result = DemoFallbackProvider().lookup(reg, client_ref_id=ref)
            result.error = "auth"
            result.response_status_id = 2
            return result

        if status_id == 4:
            logger.warning(
                "EKO vehicle-rc unavailable endpoint=vehicle-rc client_ref_id=%s response_status_id=4",
                ref,
            )
            result = DemoFallbackProvider().lookup(reg, client_ref_id=ref)
            result.timed_out = True
            result.error = "unavailable"
            result.response_status_id = 4
            return result

        if status_id not in (0, None):
            logger.warning(
                "EKO vehicle-rc status=%s endpoint=vehicle-rc client_ref_id=%s message=%s",
                status_id,
                ref,
                message,
            )
            result = DemoFallbackProvider().lookup(reg, client_ref_id=ref)
            result.error = f"status_{status_id}"
            result.response_status_id = status_id
            return result

        data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            data = {}
        make = str(
            data.get("vehicle_manufacturer_name")
            or data.get("maker")
            or data.get("make")
            or ""
        ).strip()
        model = str(data.get("model") or data.get("vehicle_model") or "").strip()
        if not make and not model:
            logger.warning(
                "EKO vehicle-rc missing make/model endpoint=vehicle-rc client_ref_id=%s",
                ref,
            )
            result = DemoFallbackProvider().lookup(reg, client_ref_id=ref)
            result.error = "empty_payload"
            result.raw_payload = payload if isinstance(payload, dict) else {"raw": str(payload)}
            return result

        blacklist_status = str(data.get("blacklist_status") or data.get("black_list_status") or "").strip()
        logger.info(
            "EKO vehicle-rc success endpoint=vehicle-rc client_ref_id=%s response_status_id=0",
            ref,
        )
        return VehicleLookupResult(
            registration_number=str(data.get("reg_no") or reg).replace(" ", "").upper(),
            make=make or "Unknown",
            model=model or "Unknown",
            year=_year_from_eko(data),
            color=str(data.get("vehicle_color") or data.get("color") or "").strip() or "—",
            fuel_type=str(data.get("fuel_type") or "").strip() or "—",
            owner_name=str(data.get("owner") or data.get("owner_name") or "").strip() or "—",
            source=SOURCE_LIVE_API,
            source_label=LABEL_LIVE_VAHAN,
            raw_payload=payload if isinstance(payload, dict) else {"raw": str(payload)},
            client_ref_id=ref,
            rc_status=str(data.get("rc_status") or "").strip() or None,
            insurance_validity=str(data.get("insurance_validity") or data.get("insurance_upto") or "").strip() or None,
            blacklist_status=blacklist_status or None,
            blacklisted=is_blacklist_flag(blacklist_status),
            response_status_id=0,
        )


def lookup_vehicle(
    registration_number: str,
    *,
    force_fallback: bool = False,
    session_id: str | None = None,
) -> VehicleLookupResult:
    reg = normalize_registration(registration_number)
    now = time.time()
    key = _cache_key(reg, session_id)
    cached = _CACHE.get(key)
    if cached and cached[0] > now:
        if not force_fallback or cached[1].source == SOURCE_DEMO_FALLBACK:
            logger.info("policy vehicle lookup cache_hit registration=%s session=%s", reg, session_id)
            return cached[1]

    fallback = DemoFallbackProvider()
    if force_fallback or not eko_configured():
        result = fallback.lookup(reg)
        _CACHE[key] = (now + _CACHE_TTL_SECONDS, result)
        return result

    try:
        result = EkoVahanProvider().lookup(reg)
    except Exception as exc:
        logger.warning("EKO vehicle lookup failed (%s) — using mimic data", type(exc).__name__)
        result = fallback.lookup(reg)
        result.error = type(exc).__name__[:240]
        result.raw_payload = {
            **(result.raw_payload or {}),
            "live_error": type(exc).__name__,
        }

    # Genuine VAHAN miss (JSON status 1) can ask the user to retype.
    # Auth, whitelist, HTTP errors, timeouts, and empty payloads always mimic.
    if result.not_found and result.response_status_id == 1 and not result.error:
        return result
    if result.error == "invalid_format":
        return result
    if result.source != SOURCE_LIVE_API:
        result.not_found = False
        result.user_notice = None
        logger.info("policy vehicle lookup mimic source=%s error=%s", result.source, result.error)

    _CACHE[key] = (now + _CACHE_TTL_SECONDS, result)
    return result
