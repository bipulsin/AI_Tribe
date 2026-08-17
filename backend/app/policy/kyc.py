"""KYC providers: mock insurer-tagged (live), plus placeholders for future modes."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol

from app.policy.constants import KYC_MODE_MOCK, LABEL_KYC_SIMULATED
from app.policy.extraction import is_valid_aadhaar, is_valid_pan, last_four, mask_id_number


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


class KycProvider(Protocol):
    def validate(
        self,
        *,
        id_type: str,
        id_number: str,
        attempt_number: int,
        rng: random.Random | None = None,
    ) -> KycResult: ...


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
        )


class InsurerApiProvider:
    """Placeholder — not configured in this build."""

    def validate(self, **kwargs) -> KycResult:
        return MockInsurerTaggedProvider().validate(**kwargs)


class LocalExtractionProvider:
    """Placeholder OCR / Vision LLM — disabled in this build."""

    def validate(self, **kwargs) -> KycResult:
        return MockInsurerTaggedProvider().validate(**kwargs)


def get_kyc_provider(mode: str) -> KycProvider:
    return MockInsurerTaggedProvider()


def mask_only(id_number: str) -> str:
    return mask_id_number(id_number)


def last4_only(id_number: str) -> str:
    return last_four(id_number)
