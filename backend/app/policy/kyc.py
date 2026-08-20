"""KYC providers: mock insurer-tagged plus live EKO PAN Lite."""

from __future__ import annotations

import logging
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.core.config import get_settings
from app.policy.constants import KYC_MODE_EKO_PAN, KYC_MODE_MOCK, LABEL_KYC_EKO_PAN, LABEL_KYC_SIMULATED
from app.policy.eko_runtime import eko_configured, prepare_eko_environ
from app.policy.extraction import is_valid_aadhaar, is_valid_pan, last_four, mask_id_number, parse_dob
from app.services.eko_auth import get_eko_headers, get_eko_initiator_id

logger = logging.getLogger("ai_tribe.policy.kyc")

_TIMEOUT_SECONDS = 10.0
PAN_VALID_STATUSES = {"E", "EA", "EC", "ED", "EI", "EL", "EM", "EP", "ES", "EU"}
PAN_INVALID_STATUSES = {"N", "X", "F", "D"}


@dataclass
class KycResult:
    valid: bool
    mode: str
    demo_mode: bool
    label: str
    reason: str | None
    id_type: str
    id_masked: str
    attempt_number: int
    name_match: str | None = None
    dob_match: str | None = None
    pan_status: str | None = None
    aadhaar_seeding_status: str | None = None
    aadhaar_seeding_status_desc: str | None = None
    match_kind: str | None = None
    client_ref_id: str | None = None
    raw_response: dict[str, Any] | None = field(default=None)
    allow_retry: bool = True
    fallback_to_mock: bool = False
    response_status_id: int | None = None
    user_notice: str | None = None


class KycProvider(Protocol):
    def validate(
        self,
        *,
        id_type: str,
        id_number: str,
        attempt_number: int,
        rng: random.Random | None = None,
    ) -> KycResult: ...


def mask_pan_display(id_number: str) -> str:
    compact = (id_number or "").replace(" ", "").upper()
    if len(compact) >= 4:
        return f"XXXX{compact[-4:]}"
    return mask_id_number(id_number)


def _yn(value: Any) -> str:
    if value in (True, "Y", "y", "yes", "YES", "true", "TRUE", 1, "1"):
        return "Y"
    if value in (False, "N", "n", "no", "NO", "false", "FALSE", 0, "0"):
        return "N"
    text = str(value or "").strip().upper()
    if text.startswith("Y"):
        return "Y"
    if text.startswith("N"):
        return "N"
    return text[:1] or ""


def _status_id(payload: dict[str, Any]) -> int | None:
    raw = payload.get("response_status_id", payload.get("status"))
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        text = str(raw).strip().upper()
        if text in {"SUCCESS", "OK", "VALID"}:
            return 0
        return None


def make_kyc_client_ref() -> str:
    return f"KYC{int(time.time())}{secrets.token_hex(2)}"[:20]


class MockInsurerTaggedProvider:
    """Zero-cost simulated KYC. First attempt ~1/5 invalid; retry always valid."""

    INVALID_REASON = "document appears unclear, please re-enter"

    def validate(
        self,
        *,
        id_type: str,
        id_number: str,
        attempt_number: int,
        rng: random.Random | None = None,
        name: str | None = None,
        dob: str | None = None,
        session_id: str | None = None,
    ) -> KycResult:
        kind = (id_type or "").strip().title()
        if kind == "Aadhar":
            kind = "Aadhaar"
        if kind == "Pan":
            kind = "PAN"
        format_ok = is_valid_pan(id_number) if kind == "PAN" else is_valid_aadhaar(id_number)
        if not format_ok:
            return KycResult(
                valid=False,
                mode=KYC_MODE_MOCK,
                demo_mode=True,
                label=LABEL_KYC_SIMULATED,
                reason="ID format is invalid. Please re-enter a valid PAN or Aadhaar.",
                id_type=kind,
                id_masked=mask_id_number(id_number),
                attempt_number=attempt_number,
            )
        dice = rng or random
        invalid = attempt_number <= 1 and dice.random() < 0.2
        return KycResult(
            valid=not invalid,
            mode=KYC_MODE_MOCK,
            demo_mode=True,
            label=LABEL_KYC_SIMULATED,
            reason=self.INVALID_REASON if invalid else None,
            id_type=kind,
            id_masked=mask_id_number(id_number),
            attempt_number=attempt_number,
            match_kind="full" if not invalid else "invalid",
        )


class EkoKycProvider:
    def __init__(self) -> None:
        prepare_eko_environ()
        self.available = eko_configured()

    def validate(
        self,
        *,
        id_type: str,
        id_number: str,
        attempt_number: int,
        rng: random.Random | None = None,
        name: str | None = None,
        dob: str | None = None,
        session_id: str | None = None,
    ) -> KycResult:
        kind = (id_type or "").strip().upper()
        if kind != "PAN" or not self.available:
            return MockInsurerTaggedProvider().validate(
                id_type=id_type,
                id_number=id_number,
                attempt_number=attempt_number,
                rng=rng,
            )
        return self.validate_pan(
            pan_number=id_number,
            name=name or "",
            dob=dob or "",
            session_id=session_id or "",
            attempt_number=attempt_number,
        )

    def validate_pan(
        self,
        *,
        pan_number: str,
        name: str,
        dob: str,
        session_id: str,
        attempt_number: int,
    ) -> KycResult:
        pan = (pan_number or "").replace(" ", "").upper()
        if not is_valid_pan(pan):
            return KycResult(
                valid=False,
                mode=KYC_MODE_EKO_PAN,
                demo_mode=False,
                label=LABEL_KYC_EKO_PAN,
                reason="PAN format is invalid. Use AAAAA9999A (for example ABCDE1234F).",
                id_type="PAN",
                id_masked=mask_pan_display(pan),
                attempt_number=attempt_number,
                allow_retry=True,
            )
        if not (name or "").strip():
            return KycResult(
                valid=False,
                mode=KYC_MODE_EKO_PAN,
                demo_mode=False,
                label=LABEL_KYC_EKO_PAN,
                reason="Customer name is required for live PAN verification.",
                id_type="PAN",
                id_masked=mask_pan_display(pan),
                attempt_number=attempt_number,
                allow_retry=True,
            )
        parsed_dob = parse_dob(dob) if dob else None
        if not parsed_dob:
            return KycResult(
                valid=False,
                mode=KYC_MODE_EKO_PAN,
                demo_mode=False,
                label=LABEL_KYC_EKO_PAN,
                reason="Date of birth must be YYYY-MM-DD for live PAN verification.",
                id_type="PAN",
                id_masked=mask_pan_display(pan),
                attempt_number=attempt_number,
                allow_retry=True,
            )

        prepare_eko_environ()
        ref = make_kyc_client_ref()
        settings = get_settings()
        try:
            headers_full = get_eko_headers()
        except RuntimeError:
            logger.critical("EKO pan-lite headers unavailable client_ref_id=%s", ref)
            return self._fallback(pan, attempt_number, ref, "auth_config")

        base_url = headers_full.pop("base-url")
        url = base_url + settings.eko_pan_lite_path
        body = {
            "initiator_id": get_eko_initiator_id(),
            "pan_number": pan,
            "name": name.strip(),
            "dob": parsed_dob,
            "client_ref_id": ref,
        }
        try:
            with httpx.Client(timeout=_TIMEOUT_SECONDS) as client:
                response = client.post(url, json=body, headers=headers_full)
        except httpx.TimeoutException:
            logger.warning("EKO pan-lite timeout endpoint=pan-lite client_ref_id=%s — immediate mimic", ref)
            return self._fallback(pan, attempt_number, ref, "timeout")
        except Exception as exc:
            logger.error(
                "EKO pan-lite network error endpoint=pan-lite client_ref_id=%s err=%s — immediate mimic",
                ref,
                type(exc).__name__,
            )
            return self._fallback(pan, attempt_number, ref, type(exc).__name__)

        try:
            payload = response.json()
        except Exception:
            payload = {"http_status": response.status_code, "text": (response.text or "")[:2000]}
        if not isinstance(payload, dict):
            payload = {"raw": str(payload)}

        status_id = _status_id(payload)
        if response.status_code != 200:
            logger.warning(
                "EKO pan-lite HTTP %s endpoint=pan-lite client_ref_id=%s — immediate mimic",
                response.status_code,
                ref,
            )
            if status_id == 2:
                logger.critical("EKO pan-lite authentication error client_ref_id=%s", ref)
            return self._fallback(pan, attempt_number, ref, f"http_{response.status_code}")

        if status_id == 1:
            return KycResult(
                valid=False,
                mode=KYC_MODE_EKO_PAN,
                demo_mode=False,
                label=LABEL_KYC_EKO_PAN,
                reason="That PAN could not be verified. Please check and retry.",
                id_type="PAN",
                id_masked=mask_pan_display(pan),
                attempt_number=attempt_number,
                client_ref_id=ref,
                raw_response=payload,
                response_status_id=1,
                allow_retry=attempt_number < 2,
                fallback_to_mock=attempt_number >= 2,
                match_kind="invalid",
            )

        if status_id == 2:
            logger.critical("EKO pan-lite authentication error client_ref_id=%s response_status_id=2", ref)
            return self._fallback(pan, attempt_number, ref, "auth")

        if status_id == 4:
            logger.warning("EKO pan-lite unavailable client_ref_id=%s response_status_id=4", ref)
            return self._fallback(pan, attempt_number, ref, "unavailable")

        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        pan_status = str(data.get("pan_status") or "").strip().upper()
        status_field = str(data.get("status") or "").strip().upper()
        name_match = _yn(data.get("name_match"))
        dob_match = _yn(data.get("dob_match"))
        seeding = str(data.get("aadhaar_seeding_status") or "").strip()
        seeding_desc = str(data.get("aadhaar_seeding_status_desc") or "").strip()

        invalid = status_field == "INVALID" or pan_status in PAN_INVALID_STATUSES
        valid_pan = status_field == "VALID" or pan_status in PAN_VALID_STATUSES or (
            pan_status.startswith("E") and pan_status not in PAN_INVALID_STATUSES
        )

        if invalid or not valid_pan:
            logger.info("EKO pan-lite invalid pan endpoint=pan-lite client_ref_id=%s response_status_id=%s", ref, status_id)
            failed = KycResult(
                valid=False,
                mode=KYC_MODE_EKO_PAN,
                demo_mode=False,
                label=LABEL_KYC_EKO_PAN,
                reason="PAN status is invalid. Please check the number and retry.",
                id_type="PAN",
                id_masked=mask_pan_display(pan),
                attempt_number=attempt_number,
                name_match=name_match or None,
                dob_match=dob_match or None,
                pan_status=pan_status or None,
                aadhaar_seeding_status=seeding or None,
                aadhaar_seeding_status_desc=seeding_desc or None,
                match_kind="invalid",
                client_ref_id=ref,
                raw_response=payload,
                response_status_id=status_id,
                allow_retry=attempt_number < 2,
                fallback_to_mock=attempt_number >= 2,
            )
            return failed

        partial = name_match == "N" or dob_match == "N"
        match_kind = "partial" if partial else "full"
        logger.info(
            "EKO pan-lite success endpoint=pan-lite client_ref_id=%s response_status_id=0 match=%s",
            ref,
            match_kind,
        )
        warning = None
        if partial:
            warning = (
                "The PAN is valid but the name or date of birth did not match exactly. "
                "The booking can still proceed but may require manual review by the insurer."
            )
        return KycResult(
            valid=True,
            mode=KYC_MODE_EKO_PAN,
            demo_mode=False,
            label=LABEL_KYC_EKO_PAN,
            reason=warning,
            id_type="PAN",
            id_masked=mask_pan_display(pan),
            attempt_number=attempt_number,
            name_match=name_match or None,
            dob_match=dob_match or None,
            pan_status=pan_status or None,
            aadhaar_seeding_status=seeding or None,
            aadhaar_seeding_status_desc=seeding_desc or None,
            match_kind=match_kind,
            client_ref_id=ref,
            raw_response=payload,
            response_status_id=status_id if status_id is not None else 0,
        )

    def _fallback(self, pan: str, attempt_number: int, ref: str, reason: str) -> KycResult:
        logger.warning("EKO pan-lite falling back to mock client_ref_id=%s reason=%s", ref, reason)
        result = MockInsurerTaggedProvider().validate(
            id_type="PAN",
            id_number=pan,
            attempt_number=max(2, attempt_number),
        )
        result.fallback_to_mock = True
        result.client_ref_id = ref
        result.valid = True
        result.match_kind = "full"
        result.reason = None
        result.user_notice = "Live PAN verification was unavailable. Using simulated verification."
        return result


class InsurerApiProvider:
    """Routes to EKO PAN Lite when configured; otherwise mock."""

    def validate(self, **kwargs) -> KycResult:
        provider = EkoKycProvider()
        if provider.available and str(kwargs.get("id_type") or "").upper() == "PAN":
            return provider.validate(**kwargs)
        return MockInsurerTaggedProvider().validate(**kwargs)


class LocalExtractionProvider:
    """Placeholder OCR / Vision LLM — disabled in this build."""

    def validate(self, **kwargs) -> KycResult:
        return MockInsurerTaggedProvider().validate(**kwargs)


def get_kyc_provider(mode: str) -> KycProvider:
    if mode == KYC_MODE_EKO_PAN:
        return EkoKycProvider()
    return MockInsurerTaggedProvider()


def mask_only(id_number: str) -> str:
    return mask_id_number(id_number)


def last4_only(id_number: str) -> str:
    return last_four(id_number)
