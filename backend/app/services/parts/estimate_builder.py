"""Build a survey estimate sheet from matched parts and damage detections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import DamageDetection, Estimate, PipelineEvent, Vehicle
from app.models.enums import Severity
from app.services.llm.constants import PRICE_DIVERGENCE_RATIO
from app.services.parts.damage_aggregation import (
    PRICING_EXTENSIVE_DAMAGE,
    assess_extensive_damage,
)
from app.services.parts.parts_matcher import (
    PRICING_MODEL_FALLBACK,
    PRICING_NEEDS_CONFIRMATION,
    PRICING_PENDING_MANUAL,
    PRICING_PROVISIONAL,
    PartMatch,
    match_detections,
)

LABOR_RATE_INR = 450.0
GST_RATE = 0.18
DEFAULT_MANUAL_LABOR_HOURS = 2.0

PRICE_DISCLAIMER = (
    "Part prices shown are indicative estimates from publicly available "
    "sources and have not been independently verified. Do not use for binding "
    "settlement decisions."
)

REPAIR_PART_FRACTION = {
    Severity.minor.value: 0.35,
    Severity.moderate.value: 0.55,
    Severity.severe.value: 0.75,
}

PRICE_SOURCE_CATALOG = "catalog"
PRICE_SOURCE_MANUAL = "manual"
PRICE_SOURCE_UNPRICED = "unpriced"
PRICE_SOURCE_LLM = "llm_suggested"


@dataclass
class BuiltEstimate:
    line_items: list[dict[str, Any]]
    subtotal: float
    tax: float
    grand_total: float
    reason_summary: str
    currency: str
    pricing_basis: str
    catalogue_vehicle_label: str
    identified_vehicle_label: str
    fallback_source_model: str | None
    identity_pricing_basis: str
    pricing_complete: bool


def _line_key(item: dict[str, Any]) -> tuple[str, str]:
    return (
        str(item.get("part_name") or ""),
        str(item.get("damage_type") or ""),
    )


def _is_line_priced(item: dict[str, Any]) -> bool:
    source = item.get("price_source")
    if source == PRICE_SOURCE_UNPRICED:
        return False
    if source in {PRICE_SOURCE_CATALOG, PRICE_SOURCE_MANUAL, PRICE_SOURCE_LLM}:
        return item.get("unit_price") is not None
    return bool(item.get("catalogue_match")) and item.get("unit_price") is not None


def _compute_line_costs(
    *,
    unit_price: float,
    labor_hours: float,
    repair_or_replace: str,
    severity: str,
) -> tuple[float, float, float]:
    action = (repair_or_replace or "repair").lower()
    if action == "replace":
        priced_unit = unit_price
        priced_labor_hours = labor_hours
    else:
        fraction = REPAIR_PART_FRACTION.get(severity, 0.55)
        priced_unit = round(unit_price * fraction, 2)
        priced_labor_hours = max(0.5, labor_hours * 0.75)

    labor_cost = round(priced_labor_hours * LABOR_RATE_INR, 2)
    total = round(priced_unit + labor_cost, 2)
    return priced_unit, labor_cost, total


def _line_costs(match: PartMatch) -> tuple[float, float, float]:
    detection = match.detection
    severity = (
        detection.severity.value
        if hasattr(detection.severity, "value")
        else str(detection.severity)
    )
    return _compute_line_costs(
        unit_price=match.unit_price,
        labor_hours=match.labor_hours,
        repair_or_replace=detection.repair_or_replace or "repair",
        severity=severity,
    )


def _recompute_totals(line_items: list[dict[str, Any]]) -> tuple[float, float, float, str]:
    priced_items = [item for item in line_items if _is_line_priced(item)]
    if not priced_items or any(not _is_line_priced(item) for item in line_items):
        return 0.0, 0.0, 0.0, line_items[0]["currency"] if line_items else "INR"

    materials_and_labor = sum(float(item["total"]) for item in priced_items)
    subtotal = round(materials_and_labor, 2)
    tax = round(subtotal * GST_RATE, 2)
    grand_total = round(subtotal + tax, 2)
    currency = priced_items[0].get("currency") or "INR"
    return subtotal, tax, grand_total, currency


def _merge_preserved_manual_prices(
    new_items: list[dict[str, Any]],
    old_items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not old_items:
        return new_items

    old_by_key = {_line_key(item): item for item in old_items}
    merged: list[dict[str, Any]] = []
    for item in new_items:
        old = old_by_key.get(_line_key(item))
        if old and old.get("price_source") == PRICE_SOURCE_MANUAL:
            merged.append({**item, **old})
        else:
            merged.append(item)
    return merged


def _price_diverges(catalog_price: float, llm_price: float) -> bool:
    if catalog_price <= 0 or llm_price <= 0:
        return False
    return abs(catalog_price - llm_price) / catalog_price > PRICE_DIVERGENCE_RATIO


def _line_from_llm_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    unit_price = float(suggestion.get("unit_price_inr") or 0.0)
    labor_hours = float(suggestion.get("labor_hours") or DEFAULT_MANUAL_LABOR_HOURS)
    severity = str(suggestion.get("severity") or Severity.moderate.value)
    repair_or_replace = str(suggestion.get("repair_or_replace") or "repair")
    priced_unit, labor_cost, total = _compute_line_costs(
        unit_price=unit_price,
        labor_hours=labor_hours,
        repair_or_replace=repair_or_replace,
        severity=severity,
    )
    return {
        "part_name": suggestion["part_name"],
        "damage_type": suggestion.get("damage_type") or "scratch",
        "severity": severity,
        "repair_or_replace": repair_or_replace,
        "currency": "INR",
        "confidence_score": 0.0,
        "catalogue_match": False,
        "match_note": suggestion.get("notes")
        or "LLM-suggested line (not catalogue-sourced)",
        "used_model_fallback": False,
        "unit_price": priced_unit if unit_price > 0 else None,
        "labor_cost": labor_cost if unit_price > 0 else None,
        "total": total if unit_price > 0 else None,
        "price_source": PRICE_SOURCE_LLM if unit_price > 0 else PRICE_SOURCE_UNPRICED,
        "llm_provider": suggestion.get("llm_provider"),
    }


def _apply_llm_suggestions(
    line_items: list[dict[str, Any]],
    suggestions: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not suggestions:
        return line_items

    by_key = {_line_key(item): item for item in line_items}
    merged = list(line_items)

    for suggestion in suggestions:
        part_name = str(suggestion.get("part_name") or "").strip()
        if not part_name:
            continue
        damage_type = str(suggestion.get("damage_type") or "scratch")
        key = (part_name, damage_type)
        llm_price = float(suggestion.get("unit_price_inr") or 0.0)

        if key in by_key:
            item = by_key[key]
            catalog_price = item.get("unit_price")
            if not _is_line_priced(item) and llm_price > 0:
                severity = item.get("severity") or Severity.moderate.value
                priced_unit, labor_cost, total = _compute_line_costs(
                    unit_price=llm_price,
                    labor_hours=float(
                        suggestion.get("labor_hours") or DEFAULT_MANUAL_LABOR_HOURS
                    ),
                    repair_or_replace=item.get("repair_or_replace") or "repair",
                    severity=severity,
                )
                item["unit_price"] = priced_unit
                item["labor_cost"] = labor_cost
                item["total"] = total
                item["price_source"] = PRICE_SOURCE_LLM
                item["llm_provider"] = suggestion.get("llm_provider")
                item["match_note"] = (
                    suggestion.get("notes")
                    or "LLM-suggested price (not catalogue-sourced)"
                )
            elif (
                catalog_price is not None
                and llm_price > 0
                and _price_diverges(float(catalog_price), llm_price)
            ):
                item["llm_suggested_unit_price"] = round(llm_price, 2)
                item["price_divergence_note"] = (
                    f"Catalogue ₹{float(catalog_price):,.0f} vs LLM "
                    f"₹{llm_price:,.0f} (> {int(PRICE_DIVERGENCE_RATIO * 100)}% apart)"
                )
                item["llm_provider"] = suggestion.get("llm_provider")
            continue

        merged.append(_line_from_llm_suggestion(suggestion))

    return merged


def _reason_summary(
    *,
    vehicle: Vehicle | None,
    line_items: list[dict[str, Any]],
    tax: float,
    grand_total: float,
    currency: str,
    pricing_basis: str,
    identity_pricing_basis: str,
    identified_vehicle_label: str,
    catalogue_vehicle_label: str,
    fallback_source_model: str | None,
    pricing_complete: bool,
    vmmr_inconsistency: str | None = None,
    llm_disclosure: str | None = None,
) -> str:
    leads: list[str] = []

    if llm_disclosure:
        leads.append(f"{llm_disclosure} ")

    if vmmr_inconsistency:
        leads.append(f"{vmmr_inconsistency} ")

    if fallback_source_model or pricing_basis == PRICING_MODEL_FALLBACK:
        identified = identified_vehicle_label
        substitute = catalogue_vehicle_label
        if fallback_source_model and vehicle and vehicle.make:
            substitute = f"{vehicle.make} {fallback_source_model}".strip()
        identified_model = (
            (vehicle.model if vehicle and vehicle.model else None)
            or identified.split()[-1]
        )
        leads.append(
            f"Identified vehicle: {identified}. A priced parts catalogue entry "
            f"for this exact model is not yet available, this estimate uses "
            f"{substitute} pricing as an interim approximation and will be "
            f"corrected once {identified_model} catalogue data is added. "
        )

    if identity_pricing_basis == PRICING_NEEDS_CONFIRMATION:
        leads.append(
            f"The model suggested {identified_vehicle_label}, but that class is "
            "in the low-confidence tier and must be confirmed by a surveyor "
            "before this estimate is treated as final. "
        )
    elif identity_pricing_basis == PRICING_PROVISIONAL and not leads:
        leads.append(
            "Vehicle identity could not be confirmed from the submitted photos, "
            f"this estimate is priced against the nearest matched catalogue entry "
            f"({catalogue_vehicle_label}) and should be treated as indicative "
            "until a surveyor confirms the vehicle. "
        )

    manual_n = sum(
        1 for item in line_items if item.get("price_source") == PRICE_SOURCE_MANUAL
    )
    llm_n = sum(1 for item in line_items if item.get("price_source") == PRICE_SOURCE_LLM)
    divergent_n = sum(1 for item in line_items if item.get("price_divergence_note"))
    unpriced_n = sum(1 for item in line_items if not _is_line_priced(item))
    if llm_n:
        leads.append(
            f"{llm_n} line item{'s' if llm_n != 1 else ''} "
            "use LLM-suggested prices (not catalogue-sourced). "
        )
    if divergent_n:
        leads.append(
            f"{divergent_n} line item{'s' if divergent_n != 1 else ''} "
            "show catalogue vs LLM price divergence. "
        )
    if manual_n:
        leads.append(
            f"{manual_n} line item{'s' if manual_n != 1 else ''} "
            "use surveyor-entered prices (not catalogue-sourced). "
        )
    if not pricing_complete and unpriced_n:
        leads.append(
            f"{unpriced_n} damaged part{'s' if unpriced_n != 1 else ''} "
            "have no catalogue price yet — enter prices manually before "
            "this total can be finalized. "
        )

    lead = "".join(leads)

    if identity_pricing_basis == PRICING_PROVISIONAL and not fallback_source_model:
        vehicle_label = catalogue_vehicle_label
    else:
        vehicle_label = identified_vehicle_label or "the assessed vehicle"
        if vehicle_label == "the assessed vehicle" and vehicle and vehicle.make:
            bits = [vehicle.make]
            if vehicle.model:
                bits.append(vehicle.model)
            if vehicle.year:
                bits.append(str(vehicle.year))
            vehicle_label = " ".join(bits)

    n = len(line_items)
    replace_n = sum(1 for item in line_items if item.get("repair_or_replace") == "replace")
    repair_n = n - replace_n
    parts = (
        f"{n} damaged part{'s' if n != 1 else ''} on {vehicle_label}"
        f" ({repair_n} repair, {replace_n} replace)"
    )

    if not pricing_complete:
        body = (
            f"{parts}. A grand total is not shown until every line has a "
            f"catalogue or manually entered price. {PRICE_DISCLAIMER}"
        )
        return f"{lead}{body}"

    materials = sum(float(item["unit_price"]) for item in line_items if _is_line_priced(item))
    labor = sum(float(item["labor_cost"]) for item in line_items if _is_line_priced(item))
    body = (
        f"Total of {currency} {grand_total:,.2f} covers {parts}. "
        f"Parts and materials come to {currency} {materials:,.2f}, "
        f"labour at ₹{LABOR_RATE_INR:.0f}/hr adds {currency} {labor:,.2f}, "
        f"and GST ({GST_RATE:.0%}) is {currency} {tax:,.2f}. "
        f"{PRICE_DISCLAIMER}"
    )
    return f"{lead}{body}"


def _extensive_damage_summary(
    *,
    escalate_reason: str,
    identity_pricing_basis: str,
    identified_vehicle_label: str,
    vmmr_inconsistency: str | None = None,
) -> str:
    leads: list[str] = []
    if vmmr_inconsistency:
        leads.append(f"{vmmr_inconsistency} ")
    leads.append(
        f"Extensive damage signal: {escalate_reason} "
        "A specific priced total has not been auto-generated. "
        "Surveyor confirmation is required before any settlement figure is shown. "
    )
    if identity_pricing_basis == PRICING_NEEDS_CONFIRMATION:
        leads.append(
            f"Vehicle identity ({identified_vehicle_label}) also needs surveyor confirmation. "
        )
    leads.append(PRICE_DISCLAIMER)
    return "".join(leads)


def _vehicle_id_inconsistency(db: Session, claim_id: int) -> str | None:
    event = db.scalar(
        select(PipelineEvent)
        .where(
            PipelineEvent.claim_id == claim_id,
            PipelineEvent.stage_key == "vehicle_id",
        )
        .order_by(PipelineEvent.id.desc())
    )
    if not event or not event.detail:
        return None
    if "inconsistent" in event.detail.lower():
        return event.detail
    return None


def _line_item_from_match(match: PartMatch) -> dict[str, Any]:
    detection = match.detection
    damage_type = (
        detection.damage_type.value
        if hasattr(detection.damage_type, "value")
        else str(detection.damage_type)
    )
    severity = (
        detection.severity.value
        if hasattr(detection.severity, "value")
        else str(detection.severity)
    )
    base = {
        "part_name": detection.part_name,
        "damage_type": damage_type,
        "severity": severity,
        "repair_or_replace": detection.repair_or_replace,
        "currency": match.currency,
        "confidence_score": float(detection.confidence_score),
        "catalogue_match": match.matched,
        "match_note": match.match_note,
        "used_model_fallback": match.used_model_fallback,
    }

    if not match.matched:
        return {
            **base,
            "unit_price": None,
            "labor_cost": None,
            "total": None,
            "price_source": PRICE_SOURCE_UNPRICED,
        }

    unit_price, labor_cost, total = _line_costs(match)
    return {
        **base,
        "unit_price": unit_price,
        "labor_cost": labor_cost,
        "total": total,
        "price_source": PRICE_SOURCE_CATALOG,
    }


def build_estimate(
    db: Session,
    claim_id: int,
    *,
    existing_line_items: list[dict[str, Any]] | None = None,
    llm_suggestions: list[dict[str, Any]] | None = None,
    llm_disclosure: str | None = None,
) -> BuiltEstimate:
    raw_detections = list(
        db.scalars(
            select(DamageDetection)
            .where(DamageDetection.claim_id == claim_id)
            .order_by(DamageDetection.id.asc())
        ).all()
    )
    escalate, escalate_reason = assess_extensive_damage(raw_detections)
    vmmr_inconsistency = _vehicle_id_inconsistency(db, claim_id)

    context = match_detections(db, claim_id)
    vehicle = db.scalar(select(Vehicle).where(Vehicle.source_claim_id == claim_id))

    if escalate:
        reason = _extensive_damage_summary(
            escalate_reason=escalate_reason,
            identity_pricing_basis=context.identity_pricing_basis,
            identified_vehicle_label=context.identified_vehicle_label,
            vmmr_inconsistency=vmmr_inconsistency,
        )
        return BuiltEstimate(
            line_items=[],
            subtotal=0.0,
            tax=0.0,
            grand_total=0.0,
            reason_summary=reason,
            currency="INR",
            pricing_basis=PRICING_EXTENSIVE_DAMAGE,
            catalogue_vehicle_label=context.catalogue_vehicle_label,
            identified_vehicle_label=context.identified_vehicle_label,
            fallback_source_model=context.fallback_source_model,
            identity_pricing_basis=context.identity_pricing_basis,
            pricing_complete=True,
        )

    line_items = [_line_item_from_match(match) for match in context.matches]
    line_items = _apply_llm_suggestions(line_items, llm_suggestions)
    line_items = _merge_preserved_manual_prices(line_items, existing_line_items)

    pricing_complete = all(_is_line_priced(item) for item in line_items) if line_items else True
    subtotal, tax, grand_total, currency = _recompute_totals(line_items)

    pricing_basis = context.pricing_basis
    if not pricing_complete:
        pricing_basis = PRICING_PENDING_MANUAL

    reason = _reason_summary(
        vehicle=vehicle,
        line_items=line_items,
        tax=tax,
        grand_total=grand_total,
        currency=currency,
        pricing_basis=pricing_basis,
        identity_pricing_basis=context.identity_pricing_basis,
        identified_vehicle_label=context.identified_vehicle_label,
        catalogue_vehicle_label=context.catalogue_vehicle_label,
        fallback_source_model=context.fallback_source_model,
        pricing_complete=pricing_complete,
        vmmr_inconsistency=vmmr_inconsistency,
        llm_disclosure=llm_disclosure,
    )

    return BuiltEstimate(
        line_items=line_items,
        subtotal=subtotal,
        tax=tax,
        grand_total=grand_total,
        reason_summary=reason,
        currency=currency,
        pricing_basis=pricing_basis,
        catalogue_vehicle_label=context.catalogue_vehicle_label,
        identified_vehicle_label=context.identified_vehicle_label,
        fallback_source_model=context.fallback_source_model,
        identity_pricing_basis=context.identity_pricing_basis,
        pricing_complete=pricing_complete,
    )


def apply_manual_line_prices(
    db: Session,
    claim_id: int,
    *,
    prices: list[dict[str, Any]],
    entered_by: int,
    entered_by_username: str,
) -> Estimate:
    estimate = db.scalar(select(Estimate).where(Estimate.claim_id == claim_id))
    if estimate is None:
        estimate = persist_estimate(db, claim_id)
        db.refresh(estimate)

    line_items = list(estimate.line_items or [])
    updates = {
        (
            str(row.get("part_name") or ""),
            str(row.get("damage_type") or ""),
        ): row
        for row in prices
    }
    now = datetime.now(timezone.utc).isoformat()

    for item in line_items:
        key = _line_key(item)
        update = updates.get(key)
        if not update:
            continue
        if _is_line_priced(item) and item.get("price_source") == PRICE_SOURCE_CATALOG:
            continue

        raw_price = update.get("unit_price")
        if raw_price is None:
            continue
        unit_price = round(float(raw_price), 2)
        if unit_price < 0:
            continue

        labor_hours = float(item.get("labor_hours") or DEFAULT_MANUAL_LABOR_HOURS)
        priced_unit, labor_cost, total = _compute_line_costs(
            unit_price=unit_price,
            labor_hours=labor_hours,
            repair_or_replace=item.get("repair_or_replace") or "repair",
            severity=item.get("severity") or Severity.moderate.value,
        )
        item["unit_price"] = priced_unit
        item["labor_cost"] = labor_cost
        item["total"] = total
        item["price_source"] = PRICE_SOURCE_MANUAL
        item["manual_price_entered_by"] = entered_by
        item["manual_price_entered_by_username"] = entered_by_username
        item["manual_price_entered_at"] = now
        item["match_note"] = "Surveyor-entered price (not catalogue-sourced)"

    pricing_complete = all(_is_line_priced(item) for item in line_items) if line_items else True
    subtotal, tax, grand_total, currency = _recompute_totals(line_items)

    built = build_estimate(db, claim_id, existing_line_items=line_items)
    estimate.line_items = [dict(item) for item in line_items]
    flag_modified(estimate, "line_items")
    estimate.subtotal = subtotal
    estimate.tax = tax
    estimate.grand_total = grand_total if pricing_complete else 0.0
    estimate.reason_summary = built.reason_summary
    estimate.pricing_basis = (
        built.pricing_basis if pricing_complete else PRICING_PENDING_MANUAL
    )
    estimate.generated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(estimate)
    return estimate


def persist_estimate(db: Session, claim_id: int) -> Estimate:
    from app.models import Claim
    from app.services.image_utils import claim_image_paths
    from app.services.llm.assist import assist_estimation

    existing = db.scalar(select(Estimate).where(Estimate.claim_id == claim_id))
    preserved = list(existing.line_items) if existing and existing.line_items else None

    llm_suggestions: list[dict[str, Any]] | None = None
    llm_disclosure: str | None = None
    claim = db.get(Claim, claim_id)
    if claim:
        paths = [path for _, path in claim_image_paths(db, claim)]
        detections = list(
            db.scalars(
                select(DamageDetection)
                .where(DamageDetection.claim_id == claim_id)
                .order_by(DamageDetection.id.asc())
            ).all()
        )
        vehicle = db.scalar(select(Vehicle).where(Vehicle.source_claim_id == claim_id))
        assist_result = assist_estimation(
            db,
            claim_id=claim_id,
            user_id=claim.created_by,
            image_paths=paths,
            vehicle=vehicle,
            detections=detections,
        )
        if assist_result:
            llm_suggestions, llm_disclosure = assist_result

    built = build_estimate(
        db,
        claim_id,
        existing_line_items=preserved,
        llm_suggestions=llm_suggestions,
        llm_disclosure=llm_disclosure,
    )

    if existing:
        existing.line_items = built.line_items
        existing.subtotal = built.subtotal
        existing.tax = built.tax
        existing.grand_total = built.grand_total
        existing.reason_summary = built.reason_summary
        existing.pricing_basis = built.pricing_basis
        existing.fallback_source_model = built.fallback_source_model
        existing.generated_at = datetime.now(timezone.utc)
        estimate = existing
    else:
        estimate = Estimate(
            claim_id=claim_id,
            line_items=built.line_items,
            subtotal=built.subtotal,
            tax=built.tax,
            grand_total=built.grand_total,
            reason_summary=built.reason_summary,
            pricing_basis=built.pricing_basis,
            fallback_source_model=built.fallback_source_model,
            generated_at=datetime.now(timezone.utc),
        )
        db.add(estimate)

    db.commit()
    db.refresh(estimate)
    return estimate
