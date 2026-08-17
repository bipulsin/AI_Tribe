"""Demo quote generation — three internal insurers, never a live insurer API."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from app.policy.constants import DEMO_INSURERS, LABEL_DEMO_QUOTE, SOURCE_DEMO_QUOTE


@dataclass
class QuoteDraft:
    insurer_code: str
    insurer_name: str
    package_type: str
    premium: float
    coverage_summary: str
    validity_note: str
    source_mode: str
    label: str


class InsurerQuoteProvider(Protocol):
    def quote(self, *, base_floor: float, load: float, randomized: bool, seed: str) -> QuoteDraft: ...


def _make_category(make: str | None) -> str:
    name = (make or "").strip().lower()
    if name in {"maruti", "hyundai", "tata", "renault", "kia"}:
        return "mass"
    if name in {"toyota", "honda", "mahindra"}:
        return "mid"
    return "premium"


def _pincode_zone_load(pincode: str | None) -> float:
    if not pincode:
        return 400.0
    first = pincode[0]
    if first in {"1", "2", "4", "5", "6"}:
        return 900.0
    return 250.0


def compute_load(
    *,
    year: int | None,
    make: str | None,
    pincode: str | None,
    previous_policy: bool | None,
) -> float:
    age = max(0, 2026 - int(year or 2020))
    load = age * 180.0
    category = _make_category(make)
    load += {"mass": 0.0, "mid": 1200.0, "premium": 2800.0}[category]
    load += _pincode_zone_load(pincode)
    if previous_policy:
        load -= 900.0
    else:
        load += 600.0
    return load


def _jitter(premium: float, *, randomized: bool, seed: str, code: str) -> float:
    if not randomized:
        return round(premium, 2)
    digest = hashlib.sha256(f"{seed}:{code}".encode()).hexdigest()
    delta = (int(digest[:4], 16) / 65535.0) * 0.08 - 0.04
    return round(premium * (1.0 + delta), 2)


class DemoInsurerA:
    spec = DEMO_INSURERS[0]

    def quote(self, *, base_floor: float, load: float, randomized: bool, seed: str) -> QuoteDraft:
        premium = _jitter(base_floor + load * 0.72, randomized=randomized, seed=seed, code="A")
        return QuoteDraft(
            insurer_code="A",
            insurer_name=self.spec["name"],
            package_type=self.spec["package"],
            premium=premium,
            coverage_summary=self.spec["coverage"],
            validity_note="Illustrative only · 7-day demo validity",
            source_mode=SOURCE_DEMO_QUOTE,
            label=LABEL_DEMO_QUOTE,
        )


class DemoInsurerB:
    spec = DEMO_INSURERS[1]

    def quote(self, *, base_floor: float, load: float, randomized: bool, seed: str) -> QuoteDraft:
        premium = _jitter(base_floor + load * 1.05, randomized=randomized, seed=seed, code="B")
        return QuoteDraft(
            insurer_code="B",
            insurer_name=self.spec["name"],
            package_type=self.spec["package"],
            premium=premium,
            coverage_summary=self.spec["coverage"],
            validity_note="Illustrative only · 7-day demo validity",
            source_mode=SOURCE_DEMO_QUOTE,
            label=LABEL_DEMO_QUOTE,
        )


class DemoInsurerC:
    spec = DEMO_INSURERS[2]

    def quote(self, *, base_floor: float, load: float, randomized: bool, seed: str) -> QuoteDraft:
        premium = _jitter(base_floor + load * 1.45, randomized=randomized, seed=seed, code="C")
        return QuoteDraft(
            insurer_code="C",
            insurer_name=self.spec["name"],
            package_type=self.spec["package"],
            premium=premium,
            coverage_summary=self.spec["coverage"],
            validity_note="Illustrative only · 7-day demo validity",
            source_mode=SOURCE_DEMO_QUOTE,
            label=LABEL_DEMO_QUOTE,
        )


PROVIDERS: tuple[InsurerQuoteProvider, ...] = (DemoInsurerA(), DemoInsurerB(), DemoInsurerC())


def generate_quotes(
    *,
    year: int | None,
    make: str | None,
    pincode: str | None,
    previous_policy: bool | None,
    floors: tuple[float, float, float],
    randomized: bool,
    seed: str,
) -> list[QuoteDraft]:
    load = compute_load(
        year=year, make=make, pincode=pincode, previous_policy=previous_policy
    )
    quotes = [
        provider.quote(base_floor=floor, load=load, randomized=randomized, seed=seed)
        for provider, floor in zip(PROVIDERS, floors, strict=True)
    ]
    quotes.sort(key=lambda q: q.premium)
    return quotes
